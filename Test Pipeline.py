"""
End-to-end pipeline tests.

Everything in our own code runs for real — the endpoint, JWT auth, the
duplicate check, encryption, the Celery task, the database writes. Only the
boundary to Azure is replaced, because testing whether Microsoft validates
credentials is not our job, and a test that needs a live subscription is slow,
costly and flaky.

Covers both directions:
  - bad credentials are rejected and nothing is saved
  - good credentials produce a real OptimizationAlert row
"""

from unittest.mock import patch, MagicMock

import pytest

from main import app
from azure_client import AzureCredentialError
from crypto import decrypt_secret
import models

from tests.test_main import client, TestingSessionLocal


# The sync task ends by calling analyze_server_efficiency.delay(), which
# publishes to the broker and returns. In production a running worker picks that
# up; in a test there is no worker, so the second half of the pipeline would
# never execute and no alert would ever be written.
#
# Eager mode makes .delay() run the task inline instead of publishing it, so one
# test can follow the chain from sync all the way to the alert row.
from tasks import celery_app
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True


FAKE_ACCOUNT = {
    "company_name": "Test Corp",
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "client_id": "22222222-2222-2222-2222-222222222222",
    "client_secret": "fake-secret-value",
    "subscription_id": "33333333-3333-3333-3333-333333333333",
}


def fake_vm(resource_id, size, location="eastus"):
    """A stand-in for an Azure VM object, with only the fields our code reads."""
    vm = MagicMock()
    vm.id = resource_id
    vm.location = location
    vm.hardware_profile.vm_size = size
    return vm


def fake_metrics_response(cpu_values):
    """Shape Azure Monitor returns: value -> timeseries -> data -> .average"""
    points = [MagicMock(average=v) for v in cpu_values]
    series = MagicMock(data=points)
    metric = MagicMock(timeseries=[series])
    return MagicMock(value=[metric])


def fake_sku(name, vcpus):
    sku = MagicMock()
    sku.resource_type = "virtualMachines"
    sku.name = name
    cap = MagicMock()
    cap.name = "vCPUs"
    cap.value = str(vcpus)
    sku.capabilities = [cap]
    return sku


# ──────────────────────────────────────────────────────── negative path

def test_link_rejects_bad_credentials():
    """Azure says no -> 400 with a message the user can act on, nothing saved."""
    with patch(
        "main.verify_azure_credentials",
        side_effect=AzureCredentialError(
            "Azure rejected these credentials. Check the tenant ID, client ID "
            "and client secret, and confirm the secret has not expired."
        ),
    ):
        response = client.post("/api/v1/accounts/link-azure", json=FAKE_ACCOUNT)

    assert response.status_code == 400
    assert "rejected these credentials" in response.json()["detail"]

    db = TestingSessionLocal()
    try:
        saved = db.query(models.CloudAccount).filter(
            models.CloudAccount.subscription_id == FAKE_ACCOUNT["subscription_id"]
        ).first()
        assert saved is None, "a rejected account must not be written to the database"
    finally:
        db.close()


def test_link_rejects_missing_role():
    """Credentials valid but no Reader role -> the message names the fix."""
    with patch(
        "main.verify_azure_credentials",
        side_effect=AzureCredentialError(
            "The credentials are valid but have no access to this subscription. "
            "Grant the app registration: Reader and Monitoring Reader."
        ),
    ):
        response = client.post("/api/v1/accounts/link-azure", json=FAKE_ACCOUNT)

    assert response.status_code == 400
    assert "Monitoring Reader" in response.json()["detail"]


# ──────────────────────────────────────────────────────── positive path

def test_link_encrypts_secret_at_rest():
    """A successful link stores ciphertext, never the plaintext secret."""
    with patch("main.verify_azure_credentials"):
        response = client.post("/api/v1/accounts/link-azure", json=FAKE_ACCOUNT)

    assert response.status_code == 201
    account_id = response.json()["account_id"]

    db = TestingSessionLocal()
    try:
        saved = db.get(models.CloudAccount, account_id)

        # The column must not contain what the user typed...
        assert saved.client_secret != FAKE_ACCOUNT["client_secret"]
        assert saved.client_secret.startswith("gAAAAA")        # Fernet prefix

        # ...but must decrypt back to it.
        assert decrypt_secret(saved.client_secret) == FAKE_ACCOUNT["client_secret"]
    finally:
        db.close()


def test_response_never_exposes_the_secret():
    """Listing accounts must not leak client_secret, however the schema evolves."""
    response = client.get("/api/v1/accounts")
    assert response.status_code == 200
    for account in response.json():
        assert "client_secret" not in account


def test_full_pipeline_writes_an_alert():
    """
    The whole chain, with only Azure faked:
    linked account -> sync task -> metrics -> CloudResource -> OptimizationAlert.

    This is the assertion that never passed before the model-name bug was fixed:
    an alert row actually reaching the database.
    """
    db = TestingSessionLocal()
    try:
        account = db.query(models.CloudAccount).filter(
            models.CloudAccount.subscription_id == FAKE_ACCOUNT["subscription_id"]
        ).first()
        assert account is not None, "run test_link_encrypts_secret_at_rest first"
        user_id = account.user_id
    finally:
        db.close()

    vms = [
        fake_vm("/subscriptions/33333333/vm-underused", "Standard_D4s_v3"),
        fake_vm("/subscriptions/33333333/vm-busy", "Standard_B2s"),
    ]

    compute = MagicMock()
    compute.virtual_machines.list_all.return_value = vms
    compute.resource_skus.list.return_value = [
        fake_sku("Standard_D4s_v3", 4),
        fake_sku("Standard_B2s", 2),
    ]

    monitor = MagicMock()
    # 3.2% average — a clearly oversized machine
    monitor.metrics.list.return_value = fake_metrics_response([2.1, 4.8, 2.7])

    with patch("tasks.build_clients", return_value=(compute, monitor)):
        from tasks import fetch_azure_vms_for_user
        fetch_azure_vms_for_user.apply(args=[user_id])

    db = TestingSessionLocal()
    try:
        resources = db.query(models.CloudResource).filter(
            models.CloudResource.resource_id.like("%vm-underused%")
        ).all()
        assert len(resources) == 1, "the VM should have been discovered and saved"

        resource = resources[0]
        assert resource.resource_type == "Standard_D4s_v3"     # real SKU, not a guess
        assert resource.allocated_cpu_cores == 4               # from resource_skus
        assert resource.average_cpu_usage_percent == pytest.approx(3.2, abs=0.1)
        assert resource.cost_per_hour is None                  # unknown, not fabricated

        alerts = db.query(models.OptimizationAlert).filter(
            models.OptimizationAlert.resource_id == resource.id
        ).all()
        assert len(alerts) >= 1, "THE REGRESSION: no alert was written"
        assert "3.2" in alerts[0].ai_recommendation
    finally:
        db.close()


def test_vm_with_no_metrics_is_skipped():
    """
    A deallocated VM returns no datapoints. That must read as 'unknown', not
    'idle' — otherwise every stopped machine gets a downsize recommendation.
    """
    db = TestingSessionLocal()
    try:
        account = db.query(models.CloudAccount).filter(
            models.CloudAccount.subscription_id == FAKE_ACCOUNT["subscription_id"]
        ).first()
        user_id = account.user_id
        alerts_before = db.query(models.OptimizationAlert).count()
    finally:
        db.close()

    compute = MagicMock()
    compute.virtual_machines.list_all.return_value = [
        fake_vm("/subscriptions/33333333/vm-stopped", "Standard_B1s")
    ]
    compute.resource_skus.list.return_value = [fake_sku("Standard_B1s", 1)]

    monitor = MagicMock()
    monitor.metrics.list.return_value = fake_metrics_response([])   # no datapoints

    with patch("tasks.build_clients", return_value=(compute, monitor)):
        from tasks import fetch_azure_vms_for_user
        fetch_azure_vms_for_user.apply(args=[user_id])

    db = TestingSessionLocal()
    try:
        resource = db.query(models.CloudResource).filter(
            models.CloudResource.resource_id.like("%vm-stopped%")
        ).first()
        assert resource is not None, "the VM should still be recorded"
        assert resource.average_cpu_usage_percent is None, "unknown must not become 0.0"

        assert db.query(models.OptimizationAlert).count() == alerts_before, \
            "a VM with no metrics must not generate a recommendation"
    finally:
        db.close()


# ──────────────────────────────────────────────────────── Gemini integration

def test_alert_uses_gemini_when_available():
    """
    A successful Gemini call must populate all three fields — including the
    CLI command, which the rule-based path cannot produce.
    """
    from ai_analyst import AIServerAnalysis

    fake_analysis = AIServerAnalysis(
        recommendation="Standard_B1s is heavily underused at 0.83% CPU; downsize to B1ls.",
        potential_savings=4.20,
        action_required="az vm resize --resource-group CLOUD-OPTIMIZER-RG "
                        "--name test-vm-01 --size Standard_B1ls",
    )

    db = TestingSessionLocal()
    try:
        before = db.query(models.OptimizationAlert).count()
    finally:
        db.close()

    with patch("tasks.analyse_resource", return_value=fake_analysis):
        from tasks import analyze_server_efficiency
        analyze_server_efficiency.apply(args=[
            1, 0.83, "/subs/x/vm-gemini", "Standard_B1s", 0.012, 1
        ])

    db = TestingSessionLocal()
    try:
        alerts = db.query(models.OptimizationAlert).all()
        assert len(alerts) == before + 1
        alert = alerts[-1]
        assert "downsize to B1ls" in alert.ai_recommendation
        assert alert.estimated_monthly_savings == 4.20
        assert "az vm resize" in alert.cli_command_to_fix
    finally:
        db.close()


def test_alert_falls_back_when_gemini_unavailable():
    """
    Gemini being down must degrade the alert, not lose it. The operator still
    learns the VM is idle; only the savings figure and command are missing.
    """
    db = TestingSessionLocal()
    try:
        before = db.query(models.OptimizationAlert).count()
    finally:
        db.close()

    with patch("tasks.analyse_resource", return_value=None):
        from tasks import analyze_server_efficiency
        analyze_server_efficiency.apply(args=[
            1, 0.83, "/subs/x/vm-fallback", "Standard_B1s", None, 1
        ])

    db = TestingSessionLocal()
    try:
        alerts = db.query(models.OptimizationAlert).all()
        assert len(alerts) == before + 1, "an alert must still be written"
        alert = alerts[-1]
        assert "0.83% CPU" in alert.ai_recommendation
        assert alert.estimated_monthly_savings is None
        assert alert.cli_command_to_fix is None
    finally:
        db.close()