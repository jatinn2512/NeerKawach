from fastapi.testclient import TestClient

from app.main import app


def test_drainage_contract_contains_connected_sample_link() -> None:
    response = TestClient(app).get("/drainage")

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["node_id"] for node in body["nodes"]}
    link = body["links"][0]
    assert link["from_node"] in node_ids
    assert link["to_node"] in node_ids
