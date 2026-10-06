"""
The only file that talks to Google Gemini.

Turns a VM's measured usage into a FinOps recommendation: an assessment, a
savings estimate, and the exact CLI command to apply the fix.

Structured output is the important part — we hand Gemini a Pydantic schema and
get typed fields back, rather than asking for prose and parsing numbers out of
a sentence.

Every failure returns None. The caller falls back to a rule-based
recommendation, so an API outage or a quota limit degrades the output instead
of losing the alert entirely.
"""

import logging
import os

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client = None


class AIServerAnalysis(BaseModel):
    """The shape we require back from Gemini. Field descriptions are part of
    the prompt — the model reads them to decide what to put where."""

    recommendation: str = Field(
        description="One or two sentences assessing this resource: is it "
                    "oversized, right-sized, or under pressure, and what should "
                    "be done. Mention any risk in acting on it."
    )
    potential_savings: float = Field(
        description="Estimated monthly saving in USD if the recommendation is "
                    "applied. 0.0 if no change is warranted or cost is unknown."
    )
    action_required: str = Field(
        description="The exact Azure CLI command to apply the fix, using the "
                    "real resource group and VM name from the resource ID. "
                    "Empty string if no action is needed."
    )


def _get_client():
    """
    Build the Gemini client on first use.

    Lazy rather than at import time so the worker still starts when
    GEMINI_API_KEY is absent — the pipeline then runs rule-based.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; falling back to rule-based recommendations.")
        return None

    from google import genai
    _client = genai.Client(api_key=api_key)
    return _client


def build_prompt(resource_id, resource_type, cpu_usage, cost_per_hour, cores, lookback_days):
    """
    The resource ID is the full Azure path, which carries the resource group and
    VM name — that is how the model can produce a runnable CLI command rather
    than a template with placeholders.
    """
    cost_line = (
        f"- Hourly cost: ${cost_per_hour}/hr"
        if cost_per_hour is not None
        else "- Hourly cost: unknown (do not invent one; use 0.0 for savings if "
             "you cannot estimate it)"
    )
    cores_line = f"- Allocated vCPUs: {cores}" if cores is not None else "- Allocated vCPUs: unknown"

    return (
        "You are an enterprise cloud FinOps architect reviewing Azure infrastructure.\n\n"
        "Resource under review:\n"
        f"- Azure resource ID: {resource_id}\n"
        f"- VM size: {resource_type}\n"
        f"{cores_line}\n"
        f"- Average CPU over the last {lookback_days} days: {cpu_usage}%\n"
        f"{cost_line}\n\n"
        "Assess whether this resource is correctly sized. If it is oversized, "
        "recommend a specific smaller Azure VM size and give the exact `az vm resize` "
        "command, taking the resource group and VM name from the resource ID above. "
        "If the workload is production-critical or the data is too thin to be "
        "confident, say so rather than recommending a change."
    )


def analyse_resource(resource_id, resource_type, cpu_usage,
                     cost_per_hour=None, cores=None, lookback_days=7):
    """
    Ask Gemini what to do about this VM.

    Returns an AIServerAnalysis, or None if the key is missing, the API fails,
    or the response cannot be parsed — the caller handles the fallback.
    """
    client = _get_client()
    if client is None:
        return None

    prompt = build_prompt(
        resource_id, resource_type, cpu_usage, cost_per_hour, cores, lookback_days
    )

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": AIServerAnalysis,
            },
        )
    except Exception as exc:
        # Quota, network, auth, model unavailable — all recoverable, because the
        # caller writes a rule-based alert instead.
        logger.warning("Gemini call failed for %s: %s", resource_id, exc)
        return None

    result = response.parsed
    if not isinstance(result, AIServerAnalysis):
        logger.warning(
            "Gemini returned an unexpected shape for %s: %r", resource_id, result
        )
        return None

    logger.info("Gemini analysis received for %s", resource_id)
    return result