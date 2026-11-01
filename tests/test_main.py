from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from database import engine, SessionLocal as TestingSessionLocal, Base

from auth import get_current_user
import models


def override_get_current_user():
    """Bypass JWT authentication and return a mock user"""
    return models.User(
        id=1, 
        email="test_admin@gmail.com", 
        department="Engineering",
        hashed_password="fake_password"
    )


app.dependency_overrides[get_current_user] = override_get_current_user

Base.metadata.create_all(bind=engine)

client = TestClient(app)


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
    
    client.post("/users/", json={
        "email": "duplicate@gmail.com",
        "department": "HR"
    })

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


def test_create_server_success():
    """Should create a server, owned by the caller, and queue analysis"""

    with patch("main.analyze_server_efficiency.delay") as mock_delay:
        response = client.post("/servers/", json={
            "resource_id": "vm-001",
            "resource_type": "VM",
            "allocated_cpu_cores": 4,
            "average_cpu_usage_percent": 15.0,
            "cost_per_hour": 0.5,
        })

        assert response.status_code == 201
        assert response.json()["resource_id"] == "vm-001"
        # The owner comes from the token, not the request body.
        assert response.json()["owner_id"] == 1

        mock_delay.assert_called_once()


def test_create_server_duplicate_resource():
    """Should return 400 if the SAME USER registers a resource twice"""

    body = {
        "resource_id": "vm-duplicate",
        "resource_type": "VM",
        "allocated_cpu_cores": 2,
        "average_cpu_usage_percent": 30.0,
        "cost_per_hour": 0.3,
    }

    with patch("main.analyze_server_efficiency.delay"):
        client.post("/servers/", json=body)
        response = client.post("/servers/", json=body)

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]




def test_get_servers():
    """Should return list of servers"""
    response = client.get("/servers/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


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