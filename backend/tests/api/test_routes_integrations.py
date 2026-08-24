"""API tests for POST /api/integrations/{platform} and related endpoints."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_celery(mocker):
    task = mocker.MagicMock()
    task.id = "test-task-id-123"
    return mocker.patch(
        "app.api.routes_integrations.ingest_platform.delay",
        return_value=task,
    )


@pytest.fixture()
def mock_reprocess(mocker):
    task = mocker.MagicMock()
    task.id = "reprocess-task-id"
    return mocker.patch(
        "app.api.routes_integrations.process_unprocessed_reviews.delay",
        return_value=task,
    )


# ---------------------------------------------------------------------------
# POST /api/integrations/{platform}
# ---------------------------------------------------------------------------


class TestTriggerIngestion:
    def test_valid_google_request_returns_queued(self, client, mock_celery):
        resp = client.post(
            "/api/integrations/google",
            json={
                "platform": "google",
                "business_name": "Test Business",
                "params": {"data_id": "0x123abc"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert resp.json()["task_id"] == "test-task-id-123"

    def test_unsupported_platform_returns_422(self, client):
        resp = client.post(
            "/api/integrations/tiktok",
            json={
                "platform": "tiktok",
                "params": {},
            },
        )
        assert resp.status_code == 422

    def test_missing_data_id_and_place_id_returns_422(self, client, mock_celery):
        resp = client.post(
            "/api/integrations/google",
            json={
                "platform": "google",
                "params": {},
            },
        )
        assert resp.status_code == 422

    def test_place_id_accepted_as_business_id(self, client, mock_celery):
        resp = client.post(
            "/api/integrations/google",
            json={
                "platform": "google",
                "business_name": "Test Business",
                "params": {"place_id": "ChIJ123"},
            },
        )
        assert resp.status_code == 200

    def test_celery_called_with_correct_args(self, client, mock_celery):
        client.post(
            "/api/integrations/google",
            json={
                "platform": "google",
                "business_name": "Test Business",
                "params": {"data_id": "0x123abc"},
            },
        )
        mock_celery.assert_called_once_with(
            "google",
            "0x123abc",
            {"data_id": "0x123abc", "place_name": "Test Business", "max_reviews": 10},
        )

    def test_max_reviews_forwarded_in_params(self, client, mock_celery):
        client.post(
            "/api/integrations/google",
            json={
                "platform": "google",
                "business_name": "Test Business",
                "max_reviews": 50,
                "params": {"data_id": "0x123"},
            },
        )
        _, _, params = mock_celery.call_args[0]
        assert params["max_reviews"] == 50


# ---------------------------------------------------------------------------
# GET /api/integrations/tasks/{task_id}
# ---------------------------------------------------------------------------


class TestGetTaskStatus:
    def test_pending_task(self, client, mocker):
        mocker.patch(
            "app.api.routes_integrations.celery_app.AsyncResult",
            return_value=mocker.MagicMock(state="PENDING"),
        )
        resp = client.get("/api/integrations/tasks/fake-id")
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"

    def test_progress_includes_stage(self, client, mocker):
        mocker.patch(
            "app.api.routes_integrations.celery_app.AsyncResult",
            return_value=mocker.MagicMock(
                state="PROGRESS",
                info={"stage": "saving", "total": 10, "saved": 4},
            ),
        )
        resp = client.get("/api/integrations/tasks/fake-id")
        body = resp.json()
        assert body["status"] == "PROGRESS"
        assert body["progress"]["stage"] == "saving"
        assert body["progress"]["total"] == 10

    def test_success_includes_result(self, client, mocker):
        mocker.patch(
            "app.api.routes_integrations.celery_app.AsyncResult",
            return_value=mocker.MagicMock(
                state="SUCCESS",
                result={"processed": 5, "skipped": 0, "rate_limited": 0, "total": 5},
            ),
        )
        resp = client.get("/api/integrations/tasks/fake-id")
        assert resp.json()["result"]["processed"] == 5

    def test_failure_returns_error_key(self, client, mocker):
        mocker.patch(
            "app.api.routes_integrations.celery_app.AsyncResult",
            return_value=mocker.MagicMock(state="FAILURE", info=Exception("boom")),
        )
        resp = client.get("/api/integrations/tasks/fake-id")
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# POST /api/integrations/reprocess
# ---------------------------------------------------------------------------


class TestReprocess:
    def test_queues_task_and_returns_task_id(self, client, mock_reprocess):
        resp = client.post("/api/integrations/reprocess")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == "reprocess-task-id"

    def test_passes_limit_param(self, client, mock_reprocess):
        client.post("/api/integrations/reprocess?limit=25")
        mock_reprocess.assert_called_once_with(limit=25)
