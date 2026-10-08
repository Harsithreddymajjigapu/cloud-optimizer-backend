"""
Shared Azure access: building credentials from a stored account, and proving a
set of credentials actually works before we agree to store it.

Both main.py (at link time) and tasks.py (at sync time) go through here, so the
decryption step can never be forgotten in one place and remembered in the other.
"""

import logging

from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient

from crypto import decrypt_secret

logger = logging.getLogger(__name__)


REQUIRED_ROLES = "Reader (for VM inventory) and Monitoring Reader (for CPU metrics)"


class AzureCredentialError(Exception):
    """Credentials are wrong, expired, or lack access. Carries a user-facing message."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def build_credential(account):
    """Build an Azure credential from a stored CloudAccount, decrypting the secret."""
    return ClientSecretCredential(
        tenant_id=account.tenant_id,
        client_id=account.client_id,
        client_secret=decrypt_secret(account.client_secret),
    )


def build_clients(account):
    """Compute and Monitor clients for one linked subscription."""
    credential = build_credential(account)
    return (
        ComputeManagementClient(credential, account.subscription_id),
        MonitorManagementClient(credential, account.subscription_id),
    )


def verify_azure_credentials(tenant_id, client_id, client_secret, subscription_id):
    """
    Prove the credentials work before they are stored.

    Listing VMs checks all four fields at once: the three credentials
    authenticate, and the subscription ID is real and readable.

    Raises AzureCredentialError with a message that says what to fix.
    """
    try:
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        client = ComputeManagementClient(credential, subscription_id)

        # list_all() is a lazy paged iterator — nothing reaches Azure until it
        # is iterated. Without this next(), invalid credentials would pass.
        next(iter(client.virtual_machines.list_all()), None)

    except ValueError as exc:
        # The SDK validates the shape of the tenant and client IDs locally,
        # before any network call, and raises a bare ValueError. Without this
        # branch it escapes as a 500 — so a typo'd GUID would give the user a
        # stack trace while a wrong password gave a readable message.
        raise AzureCredentialError(
            f"One of the IDs is not in a valid format: {exc}. "
            "Tenant ID, client ID and subscription ID must each be a GUID, "
            "for example 084a029e-1234-5678-9abc-def012345678."
        )
    except ClientAuthenticationError:
        raise AzureCredentialError(
            "Azure rejected these credentials. Check the tenant ID, client ID "
            "and client secret, and confirm the secret has not expired."
        )
    except HttpResponseError as exc:
        if exc.status_code == 403:
            raise AzureCredentialError(
                "The credentials are valid but have no access to this "
                f"subscription. Grant the app registration: {REQUIRED_ROLES}."
            )
        if exc.status_code == 404:
            raise AzureCredentialError(
                "That subscription ID was not found for this tenant. "
                "Check the subscription ID."
            )
        raise AzureCredentialError(f"Could not reach this subscription: {exc.reason}")


def verify_metrics_access(monitor_client, resource_uri):
    """
    Confirm the Monitoring Reader role by reading one metric.

    Listing VMs only proves Reader. This needs a real resource to query, so it
    can only run once the subscription has at least one VM. Returns True/False
    rather than raising — missing metrics access degrades the product, it does
    not break it.
    """
    try:
        monitor_client.metrics.list(
            resource_uri=resource_uri,
            metricnames="Percentage CPU",
            aggregation="Average",
        )
        return True
    except HttpResponseError as exc:
        logger.warning(
            "No metrics access for %s (%s). Grant: %s",
            resource_uri, exc.status_code, REQUIRED_ROLES,
        )
        return False