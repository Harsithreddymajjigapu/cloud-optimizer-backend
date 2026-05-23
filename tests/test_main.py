import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from main import app
from database import get_db, Base

# ──────────────────────────────────────────
# TEST DATABASE SETUP
# Uses a separate SQLite DB for tests
# so we never touch the real PostgreSQL DB
# ──────────────────────────────────────────

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Replace real DB with test DB for all tests"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override real DB with test DB
app.dependency_overrides[get_db] = override_get_db

# Create test tables
Base.metadata.create_all(bind=engine)

# Test client
client = TestClient(app)


# ──────────────────────────────────────────
# USER TESTS
# ──────────────────────────────────────────

def test_create_user_success():
    """Should create a user and return 201"""
    response = client.post("/users/", json={
        "email": "testuser@gmail.com",
        "department": "Engineering"
    })
    assert response.status_code == 201
    assert response.json()["email"] == "testuser@gmail.com"


def test_create_user_duplicate_email():
    """Should return 400 if email already exists"""
    # First creation
    client.post("/users/", json={
        "email": "duplicate@gmail.com",
        "department": "HR"
    })

    # Second creation with same email
    response = client.post("/users/", json={
        "email": "duplicate@gmail.com",
        "department": "HR"
    })
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


def test_get_users():
    """Should return list of users"""
    response = client.get("/users/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ──────────────────────────────────────────
# SERVER TESTS
# ──────────────────────────────────────────

def test_create_server_success():
    """Should create a server and queue analysis task"""

    # First create a user
    user_response = client.post("/users/", json={
        "email": "serverowner@gmail.com",
        "department": "DevOps"
    })
    user_id = user_response.json()["id"]

    # Mock .delay() so we don't actually call Redis in tests
    with patch("main.analyze_server_efficiency.delay") as mock_delay:
        response = client.post("/servers/", json={
            "resource_id": "vm-001",
            "resource_type": "VM",
            "allocated_cpu_cores": 4,
            "average_cpu_usage_percent": 15.0,
            "cost_per_hour": 0.5,
            "owner_id": user_id
        })

        assert response.status_code == 201
        assert response.json()["resource_id"] == "vm-001"

        # Confirm .delay() was called once
        mock_delay.assert_called_once()


def test_create_server_duplicate_resource():
    """Should return 400 if resource already registered"""

    # Create a user first
    user_response = client.post("/users/", json={
        "email": "owner2@gmail.com",
        "department": "Cloud"
    })
    user_id = user_response.json()["id"]

    with patch("main.analyze_server_efficiency.delay"):
        # First registration
        client.post("/servers/", json={
            "resource_id": "vm-duplicate",
            "resource_type": "VM",
            "allocated_cpu_cores": 2,
            "average_cpu_usage_percent": 30.0,
            "cost_per_hour": 0.3,
            "owner_id": user_id
        })

        # Second registration with same resource_id
        response = client.post("/servers/", json={
            "resource_id": "vm-duplicate",
            "resource_type": "VM",
            "allocated_cpu_cores": 2,
            "average_cpu_usage_percent": 30.0,
            "cost_per_hour": 0.3,
            "owner_id": user_id
        })

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]


def test_create_server_invalid_owner():
    """Should return 404 if owner user does not exist"""
    response = client.post("/servers/", json={
        "resource_id": "vm-999",
        "resource_type": "VM",
        "allocated_cpu_cores": 2,
        "average_cpu_usage_percent": 50.0,
        "cost_per_hour": 0.3,
        "owner_id": 99999  # non existent user
    })
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_servers():
    """Should return list of servers"""
    response = client.get("/servers/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ──────────────────────────────────────────
# ALERT TESTS
# ──────────────────────────────────────────

def test_get_alerts():
    """Should return list of alerts"""
    response = client.get("/alerts/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_alerts_for_invalid_resource():
    """Should return 404 for non existent resource"""
    response = client.get("/alerts/99999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]