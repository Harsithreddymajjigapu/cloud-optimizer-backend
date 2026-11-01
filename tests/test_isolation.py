"""
Tenant isolation: one user must never see or touch another user's data.

Every test here failed before the owner filters were added. They are written
from the attacker's side — a second user who owns nothing, asking for things
that are not theirs — because that is how the bug was actually found: a brand
new account, registered seconds earlier, was handed every alert in the
database.

The product allows many users to link many Azure subscriptions, so "it's only
me using it" is not a defence: the data model has user_id columns precisely
because it was never meant to be single-tenant.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from auth import get_current_user
import models

from tests.test_main import client, TestingSessionLocal, override_get_current_user


OWNER_ID = 1          # who tests/test_main.py authenticates as
INTRUDER_ID = 2       # a second user who owns nothing


def as_user(user_id, email):
    """Swap the authenticated caller for the duration of a `with` block."""

    class _Swap:
        def __enter__(self):
            app.dependency_overrides[get_current_user] = lambda: models.User(
                id=user_id, email=email, department="Other",
                hashed_password="x",
            )
            return TestClient(app)

        def __exit__(self, *exc):
            app.dependency_overrides[get_current_user] = override_get_current_user
            return False

    return _Swap()


def seed_owned_resource_with_alert(resource_id="vm-owned-by-1"):
    """Give user 1 a resource and an alert, straight into the database."""
    db = TestingSessionLocal()
    try:
        resource = models.CloudResource(
            owner_id=OWNER_ID,
            resource_id=resource_id,
            resource_type="Standard_D4s_v3",
            allocated_cpu_cores=4,
            average_cpu_usage_percent=3.1,
            cost_per_hour=0.192,
        )
        db.add(resource)
        db.commit()
        db.refresh(resource)

        alert = models.OptimizationAlert(
            resource_id=resource.id,
            ai_recommendation="SECRET: user 1's production database is idle.",
            estimated_monthly_savings=42.0,
            cli_command_to_fix="az vm resize --name user1-prod-db --size Standard_B2s",
        )
        db.add(alert)
        db.commit()
        return resource.id
    finally:
        db.close()


# ─────────────────────────────────────────────────────────── reads

def test_alerts_are_not_visible_to_another_user():
    """The exact leak: a new account seeing someone else's recommendations."""
    seed_owned_resource_with_alert("vm-alert-isolation")

    with as_user(INTRUDER_ID, "intruder@example.com") as intruder:
        response = intruder.get("/alerts/")

    assert response.status_code == 200
    body = response.json()
    leaked = [a for a in body if "SECRET" in (a.get("ai_recommendation") or "")]
    assert leaked == [], f"user {INTRUDER_ID} read user {OWNER_ID}'s alerts: {leaked}"


def test_servers_are_not_visible_to_another_user():
    """Resource IDs name real infrastructure; they are not public either."""
    seed_owned_resource_with_alert("vm-server-isolation")

    with as_user(INTRUDER_ID, "intruder@example.com") as intruder:
        response = intruder.get("/servers/")

    assert response.status_code == 200
    ids = [s["resource_id"] for s in response.json()]
    assert "vm-server-isolation" not in ids, f"leaked resources: {ids}"


def test_cannot_read_another_users_resource_alerts_by_id():
    """
    Walking ids 1,2,3... used to return every resource's alerts.

    The answer must be 404, not 403: a 403 confirms the id exists, which tells
    an attacker exactly which numbers are worth trying.
    """
    resource_id = seed_owned_resource_with_alert("vm-byid-isolation")

    with as_user(INTRUDER_ID, "intruder@example.com") as intruder:
        response = intruder.get(f"/alerts/{resource_id}")

    assert response.status_code == 404, (
        f"expected 404 for someone else's resource, got {response.status_code}"
    )


def test_users_endpoint_returns_only_the_caller():
    """It used to return every registered email address."""
    with as_user(INTRUDER_ID, "intruder@example.com") as intruder:
        response = intruder.get("/users/")

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()]
    assert emails == ["intruder@example.com"], f"leaked users: {emails}"


# ─────────────────────────────────────────────────────────── writes

def test_cannot_create_a_resource_owned_by_someone_else():
    """
    owner_id in the request body must be ignored, not honoured.

    This replaces test_create_server_invalid_owner, which asserted the opposite
    and so locked the bug in place.
    """
    with as_user(INTRUDER_ID, "intruder@example.com") as intruder:
        with patch("main.analyze_server_efficiency.delay"):
            response = intruder.post("/servers/", json={
                "resource_id": "vm-ownership-forgery",
                "resource_type": "VM",
                "allocated_cpu_cores": 2,
                "average_cpu_usage_percent": 10.0,
                "cost_per_hour": 0.1,
                "owner_id": OWNER_ID,        # forged
            })

    assert response.status_code == 201
    assert response.json()["owner_id"] == INTRUDER_ID, (
        "the owner came from the request body instead of the token"
    )


def test_two_users_can_each_own_the_same_azure_resource():
    """
    Colleagues sharing a subscription must each get their own row.

    resource_id used to be globally unique, so the second user's sync updated
    the first user's row and created none of their own — their alerts list
    stayed empty forever while the sync reported success.
    """
    shared = "/subscriptions/shared/providers/virtualMachines/shared-vm"

    with patch("main.analyze_server_efficiency.delay"):
        body = {
            "resource_id": shared,
            "resource_type": "Standard_B2s",
            "allocated_cpu_cores": 2,
            "average_cpu_usage_percent": 12.0,
            "cost_per_hour": 0.05,
        }
        first = client.post("/servers/", json=body)

        with as_user(INTRUDER_ID, "colleague@example.com") as colleague:
            second = colleague.post("/servers/", json=body)

    assert first.status_code == 201
    assert second.status_code == 201, (
        "the second user could not register a VM the first user had already seen"
    )
    assert first.json()["owner_id"] == OWNER_ID
    assert second.json()["owner_id"] == INTRUDER_ID
    assert first.json()["id"] != second.json()["id"], "they must be separate rows"