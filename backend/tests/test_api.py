from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_application_import_and_startup() -> None:
    assert app.title == "Neer Kawach API"
    with TestClient(app) as started_client:
        assert started_client.get("/health").status_code == 200


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["message"] == "Neer Kawach backend is running."


def test_flood_map() -> None:
    response = client.get("/flood/map?horizon_hours=1.5")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mock"
    assert body["is_mock"] is True
    assert body["horizon_hours"] == 1.5
    assert body["layers"]


def test_flood_risk() -> None:
    response = client.get("/flood/risk")

    assert response.status_code == 200
    assert response.json()["status"] == "mock"
    assert response.json()["alerts"]


def test_safer_route() -> None:
    response = client.get("/route/safer")

    assert response.status_code == 200
    assert response.json()["status"] == "mock"
    assert response.json()["segments"]


def test_drainage() -> None:
    response = client.get("/drainage")

    assert response.status_code == 200
    assert response.json()["status"] == "mock"
    assert response.json()["nodes"]
    assert response.json()["links"]


def test_mock_storm_run_with_operator_role() -> None:
    response = client.post(
        "/storms/run",
        headers={"X-Mock-Role": "operator"},
        json={"storm_name": "demo", "rainfall_mm": 40, "duration_minutes": 30},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "mock"
    assert body["requested_by"]["role"] == "operator"
    assert body["storm_name"] == "demo"


def test_mock_auth_rejects_viewer_for_storm_run() -> None:
    response = client.post(
        "/storms/run",
        headers={"X-Mock-Role": "viewer"},
        json={"storm_name": "demo"},
    )

    assert response.status_code == 403


def test_storm_request_validation() -> None:
    response = client.post(
        "/storms/run",
        headers={"X-Mock-Role": "operator"},
        json={"storm_name": "demo", "rainfall_mm": -1},
    )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
