from pathlib import Path

import pytest

from agent_run.errors import AgentRunError
from agent_run.task_parse import load_task
from agent_run.git_ops import slugify
from agent_run.openrouter import extract_json_object
from agent_run.test_classify import error_hash, is_runner_or_syntax_failure


def test_slugify():
    assert slugify("Implement Greet.md") == "implement-greet"


def test_load_task_ok(tmp_path: Path):
    p = tmp_path / "t.md"
    p.write_text(
        "## Task\nDo it\n\n## Constraints\nNone\n\n## Acceptance Criteria\n- works\n",
        encoding="utf-8",
    )
    doc = load_task(p)
    assert "Do it" in doc.task


def test_load_task_missing_section(tmp_path: Path):
    p = tmp_path / "t.md"
    p.write_text("## Task\nDo it\n", encoding="utf-8")
    with pytest.raises(AgentRunError):
        load_task(p)


def test_extract_json_fenced():
    data = extract_json_object('```json\n{"status": "OK", "questions": []}\n```')
    assert data["status"] == "OK"


def test_runner_failure_detection():
    assert is_runner_or_syntax_failure("SyntaxError: invalid syntax")
    assert not is_runner_or_syntax_failure("AssertionError: expected Hello")


def test_error_hash_stable():
    a = error_hash("fail at 2024-01-01T12:00:00Z boom")
    b = error_hash("fail at 2024-01-02T99:99:99Z boom")
    assert a == b
