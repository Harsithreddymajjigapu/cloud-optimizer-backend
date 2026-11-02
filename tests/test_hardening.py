"""
Regression tests for the defects found in the 1 November review.

Each of these was a real bug that the existing suite did not catch. Two of them
were demonstrated as working attacks against a running instance before being
fixed.
"""

import os
import subprocess
import sys

from unittest.mock import patch

from tests.test_main import client


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_without(var):
    """Import the app in a fresh interpreter with one env var removed."""
    env = {k: v for k, v in os.environ.items() if k != var}
    env["PYTHONPATH"] = REPO_ROOT
    return subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


# ───────────────────────────────────────────── refuse to start insecurely

def test_app_refuses_to_start_without_secret_key():
    """
    SECRET_KEY used to have a hardcoded default that lives in auth.py in a
    public repository.

    With that default, an instance deployed without the variable set would
    start up and accept tokens signed with a string anyone can read. Forging
    {"sub": "<victim email>"} was enough to read that customer's linked
    subscriptions, with no password involved — this was demonstrated against a
    running instance.

    Refusing to start is the correct failure. A service that silently runs
    without authentication is worse than one that does not run.
    """
    result = _run_without("SECRET_KEY")

    assert result.returncode != 0, "the app started with no SECRET_KEY"
    assert "SECRET_KEY is not set" in result.stderr


def test_app_refuses_to_start_without_database_url():
    """
    The DATABASE_URL fallback used to carry the real local database password in
    source. Credentials do not belong in a file that gets pushed, and a wrong
    fallback only moves the failure somewhere more confusing.
    """
    result = _run_without("DATABASE_URL")

    assert result.returncode != 0, "the app started with no DATABASE_URL"
    assert "DATABASE_URL is not set" in result.stderr


def test_no_password_is_hardcoded_in_source():
    """
    Guards against a credential being reintroduced into a tracked file. .env is
    gitignored; .py files are not, and git history cannot be un-published.
    """
    import pathlib

    offenders = []
    for path in pathlib.Path(REPO_ROOT).glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in ("huhuhu", "fallback-secret" + "-key"):
            if marker in text:
                offenders.append(f"{path.name}: {marker}")

    assert offenders == [], f"credential found in tracked source: {offenders}"


# ───────────────────────────────────────────── registration validation

def test_registration_rejects_a_malformed_email():
    """"not-an-email" used to register with a 201, then break GET /users/."""
    response = client.post("/auth/register", json={
        "email": "not-an-email", "password": "a-long-enough-password",
    })
    assert response.status_code == 422


def test_registration_rejects_a_trivial_password():
    """A one-character password used to be accepted."""
    response = client.post("/auth/register", json={
        "email": "shortpw@example.com", "password": "x",
    })
    assert response.status_code == 422


def test_user_without_a_department_can_be_listed():
    """
    department is nullable in the database and optional at registration, but
    UserResponse required it — so anyone who signed up without one made
    GET /users/ return 500. The row was fine; the response model refused to
    describe it.
    """
    created = client.post("/auth/register", json={
        "email": "nodept@example.com", "password": "a-long-enough-password",
    })
    assert created.status_code == 201

    response = client.get("/users/")
    assert response.status_code == 200, "a null department must not be a 500"


# ───────────────────────────────────────────── credential rotation

def test_rotation_rejects_an_empty_secret():
    """
    PUT {"client_secret": ""} used to return 200 having verified the OLD secret
    and then stored an empty one.

    Two lines disagreed about what "" meant: the verification step read it as
    "unchanged", the save step read it as "a value was supplied". Afterwards
    every sync failed to authenticate, and the worker's broad except swallowed
    it — stale data, no error, indefinitely.
    """
    account = {
        "company_name": "Rotation Test",
        "tenant_id": "55555555-5555-5555-5555-555555555555",
        "client_id": "66666666-6666-6666-6666-666666666666",
        "client_secret": "the-original-secret",
        "subscription_id": "77777777-7777-7777-7777-777777777777",
    }

    with patch("main.verify_azure_credentials"):
        created = client.post("/api/v1/accounts/link-azure", json=account)
    assert created.status_code == 201, created.text