from fastapi.testclient import TestClient

from src.api.app import create_app
from src.services.feedback_service import FeedbackService
from src.services.quality_service import QualityService


def test_quality_service_scores_outline_reference_coverage():
    score = QualityService().score_outline(
        outline_markdown="# Derivatives\n\nSee source [p.1]",
        required_terms=["Derivatives"],
        source_count=1,
    )

    assert score.metric == "outline_reference_coverage"
    assert score.score == 1.0


def test_feedback_service_creates_review_task_for_low_rating():
    service = FeedbackService()

    feedback = service.submit_feedback(
        target_type="question",
        target_id="q-1",
        rating=1,
        reason="incorrect_answer",
        comment="The derivative answer is wrong.",
        created_by="user-1",
    )

    review_tasks = service.list_review_tasks()
    assert feedback.rating == 1
    assert review_tasks[0].target_id == "q-1"
    assert review_tasks[0].status == "open"


def test_feedback_api_creates_review_task_and_accepts_decision():
    client = TestClient(create_app())

    feedback_response = client.post(
        "/api/feedback",
        json={
            "target_type": "question",
            "target_id": "q-1",
            "rating": 1,
            "reason": "incorrect_answer",
            "comment": "The derivative answer is wrong.",
            "created_by": "user-1",
        },
    )

    assert feedback_response.status_code == 200
    assert feedback_response.json() == {
        "id": "feedback:1",
        "rating": 1,
        "target_id": "q-1",
    }

    review_response = client.get("/api/review-tasks")

    assert review_response.status_code == 200
    review_tasks = review_response.json()
    assert review_tasks[0]["target_id"] == "q-1"
    assert review_tasks[0]["status"] == "open"

    decision_response = client.post(
        f"/api/review-tasks/{review_tasks[0]['id']}/decision",
        json={"decision": "accept", "comment": "Will revise."},
    )

    assert decision_response.status_code == 200
    assert decision_response.json() == {
        "id": review_tasks[0]["id"],
        "status": "decided",
        "decision": "accept",
    }


def test_feedback_api_state_isolated_per_app_instance():
    first_client = TestClient(create_app())
    second_client = TestClient(create_app())

    first_client.post(
        "/api/feedback",
        json={
            "target_type": "question",
            "target_id": "q-1",
            "rating": 1,
            "reason": "incorrect_answer",
            "comment": "The derivative answer is wrong.",
            "created_by": "user-1",
        },
    )

    assert first_client.get("/api/review-tasks").json()[0]["target_id"] == "q-1"
    assert second_client.get("/api/review-tasks").json() == []
