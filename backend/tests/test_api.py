from fastapi.testclient import TestClient

from app import main
from app.security import hash_password, verify_password
from conftest import register


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_and_authentication(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    token, _ = register(client, "researcher@example.org")
    assert client.get("/api/auth/me", headers=auth(token)).json()["role"] == "researcher"
    assert client.get("/api/dashboard").status_code == 401


def test_password_hash_is_salted_and_verified() -> None:
    first = hash_password("password-1234")
    second = hash_password("password-1234")
    assert first != second
    assert verify_password("password-1234", first)
    assert not verify_password("incorrect-password", first)


def test_duplicate_experiment_version_is_rejected(client: TestClient) -> None:
    token, _ = register(client, "duplicate@example.org")
    payload = {
        "name": "First run",
        "model_name": "decision_tree",
        "version": 1,
    }
    assert client.post("/api/experiments/train", headers=auth(token), json=payload).status_code == 202
    conflict = client.post("/api/experiments/train", headers=auth(token), json=payload)
    assert conflict.status_code == 409


def test_train_hash_verify_and_detect_tampering(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    token, _ = register(client, "integrity@example.org")
    response = client.post(
        "/api/experiments/train",
        headers=auth(token),
        json={
            "name": "Integrity demo",
            "model_name": "logistic_regression",
            "random_seed": 13,
        },
    )
    assert response.status_code == 202
    experiment_id = response.json()["experiment_id"]
    experiment = client.get(
        f"/api/experiments/{experiment_id}", headers=auth(token)
    ).json()
    assert experiment["status"] == "completed"
    assert experiment["manifest_hash"].startswith("sha256:")
    assert {item["type"] for item in experiment["artifacts"]} == {
        "dataset",
        "model",
        "configuration",
        "environment",
        "metrics",
        "source_reference",
        "source_code_snapshot",
        "manifest",
    }

    monkeypatch.setattr(main, "verify_manifest", lambda *args: {
        "configured": True,
        "exists": True,
        "manifest_matches": True,
        "matches": True,
        "chain_id": 31337,
    })
    valid = client.post(
        f"/api/experiments/{experiment_id}/verify", headers=auth(token)
    ).json()
    assert valid["artifacts_match"] is True
    assert valid["chain_match"] is True

    model_artifact = next(item for item in experiment["artifacts"] if item["type"] == "model")
    artifact_path = (
        tmp_path
        / "artifacts"
        / experiment["owner_id"]
        / experiment_id
        / model_artifact["file_name"]
    )
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")
    invalid = client.post(
        f"/api/experiments/{experiment_id}/verify", headers=auth(token)
    ).json()
    assert invalid["artifacts_match"] is False
    assert invalid["verified"] is False
    assert invalid["missing_artifact_types"] == []
    assert next(item for item in invalid["artifact_checks"] if item["file_name"] == "model.joblib")["matches"] is False
    dataset_path = artifact_path.with_name("dataset.csv")
    dataset_path.unlink()
    missing = client.post(
        f"/api/experiments/{experiment_id}/verify", headers=auth(token)
    ).json()
    assert missing["artifacts_match"] is False
    assert next(item for item in missing["artifact_checks"] if item["file_name"] == "dataset.csv")["exists"] is False


def test_reproduction_score_and_changed_configuration(client: TestClient) -> None:
    token, _ = register(client, "reproduce@example.org")
    created = client.post(
        "/api/experiments/train",
        headers=auth(token),
        json={"name": "Reproduction demo", "model_name": "decision_tree", "random_seed": 9},
    )
    experiment_id = created.json()["experiment_id"]
    attempt = client.post(
        f"/api/experiments/{experiment_id}/reproductions",
        headers=auth(token),
        json={},
    )
    assert attempt.status_code == 202
    result = client.get(
        f"/api/reproductions/{attempt.json()['reproduction_id']}", headers=auth(token)
    ).json()
    assert result["status"] == "completed"
    assert result["score"]["components"]["configuration_match"] == 20
    assert result["score"]["components"]["metric_agreement"] == 30
    assert len(result["metric_comparison"]) == 5
    assert all(item["within_tolerance"] for item in result["metric_comparison"])

    changed = client.post(
        f"/api/experiments/{experiment_id}/reproductions",
        headers=auth(token),
        json={"random_seed": 10},
    )
    assert changed.status_code == 202
    changed_result = client.get(
        f"/api/reproductions/{changed.json()['reproduction_id']}", headers=auth(token)
    ).json()
    assert changed_result["status"] == "completed"
    assert changed_result["score"]["components"]["configuration_match"] == 0


def test_private_experiment_is_not_visible_to_another_researcher(client: TestClient) -> None:
    owner_token, _ = register(client, "owner@example.org")
    other_token, _ = register(client, "other@example.org")
    response = client.post(
        "/api/experiments/train",
        headers=auth(owner_token),
        json={"name": "Private run", "model_name": "decision_tree"},
    )
    experiment_id = response.json()["experiment_id"]
    forbidden = client.get(
        f"/api/experiments/{experiment_id}", headers=auth(other_token)
    )
    assert forbidden.status_code == 404


def test_report_is_downloadable_json(client: TestClient) -> None:
    token, _ = register(client, "report@example.org")
    response = client.post(
        "/api/experiments/train",
        headers=auth(token),
        json={"name": "Report run", "model_name": "decision_tree"},
    )
    experiment_id = response.json()["experiment_id"]
    report = client.get(
        f"/api/experiments/{experiment_id}/report", headers=auth(token)
    )
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("application/json")
    assert report.headers["content-disposition"].endswith(
        f'experiment-{experiment_id}-report.json"'
    )
    assert report.json()["manifest_hash"].startswith("sha256:")


def test_unsupported_preprocessing_is_rejected(client: TestClient) -> None:
    token, _ = register(client, "validation@example.org")
    response = client.post(
        "/api/experiments/train",
        headers=auth(token),
        json={
            "name": "Unsupported preprocessing",
            "model_name": "decision_tree",
            "preprocessing": ["execute_uploaded_script"],
        },
    )
    assert response.status_code == 422
