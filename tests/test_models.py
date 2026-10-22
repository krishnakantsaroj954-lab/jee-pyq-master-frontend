import pytest
from typing import Any
from jee_pyq_pipeline.models import Issue, Asset, Question

def test_issue_instantiation():
    issue = Issue(code="ERR001", message="Test message")
    assert issue.code == "ERR001"
    assert issue.message == "Test message"
    assert issue.blocking is True
    assert issue.question_id is None

def test_asset_instantiation():
    asset = Asset(
        object_key="key123",
        page=1,
        bounds=[0.1, 0.2, 0.3, 0.4],
        sha256="hash123",
        path="/path/to/asset"
    )
    assert asset.object_key == "key123"
    assert asset.page == 1
    assert asset.bounds == [0.1, 0.2, 0.3, 0.4]
    assert asset.sha256 == "hash123"
    assert asset.path == "/path/to/asset"

def test_question_instantiation_and_defaults():
    question = Question(
        id="q1",
        source_question_number=1,
        text="What is 2+2?",
        options={"A": "1", "B": "2", "C": "3", "D": "4"},
        answer="D",
        pages=[1],
        bounds=[0.0, 0.0, 1.0, 1.0],
        provenance={"source": "test"}
    )
    assert question.id == "q1"
    assert question.source_question_number == 1
    assert question.assets == []
    assert question.solution is None
    assert question.requires_figure is False
    assert question.status == "VALIDATED"
    assert question.issues == []
    assert question.subject is None
    assert question.section is None
    assert question.question_type == "UNKNOWN"
    assert question.solution_assets == []

def test_question_json_serialization():
    issue1 = Issue(code="W001", message="Warning 1", blocking=False)
    issue2 = Issue(code="E001", message="Error 1", question_id="q2")
    asset1 = Asset(object_key="obj1", page=1, bounds=[0,0,1,1], sha256="abc", path="p1")
    asset2 = Asset(object_key="obj2", page=2, bounds=[1,1,2,2], sha256="def", path="p2")

    question = Question(
        id="q2",
        source_question_number=2,
        text="Sample text",
        options={"A": "Option A"},
        answer="A",
        pages=[1, 2],
        bounds=[0.1, 0.2, 0.3, 0.4],
        provenance={"exam": "JEE"},
        assets=[asset1],
        issues=[issue1, issue2],
        solution_assets=[asset2]
    )

    json_data = question.json()

    assert json_data["id"] == "q2"
    assert json_data["source_question_number"] == 2

    # Check issues serialization (which has a custom override)
    assert len(json_data["issues"]) == 2
    assert json_data["issues"][0]["code"] == "W001"
    assert json_data["issues"][0]["blocking"] is False
    assert json_data["issues"][1]["code"] == "E001"
    assert json_data["issues"][1]["blocking"] is True

    # Check assets (handled by asdict)
    assert len(json_data["assets"]) == 1
    assert json_data["assets"][0]["object_key"] == "obj1"

    # Check solution_assets (handled by asdict)
    assert len(json_data["solution_assets"]) == 1
    assert json_data["solution_assets"][0]["object_key"] == "obj2"
