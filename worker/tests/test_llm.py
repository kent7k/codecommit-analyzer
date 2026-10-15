import pytest

from analyzer.jobs import job_id_for
from analyzer.llm import Analyzer, ChunkAnalysis


def test_parse_json_plain() -> None:
    assert Analyzer.parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced() -> None:
    text = 'Here you go:\n```json\n{"components": []}\n```\n'
    assert Analyzer.parse_json(text) == {"components": []}


def test_parse_json_missing() -> None:
    with pytest.raises(ValueError):
        Analyzer.parse_json("nothing here")


def test_chunk_schema_defaults() -> None:
    a = ChunkAnalysis.model_validate({"components": [{"name": "api", "summary": "s"}]})
    assert a.components[0].kind == "other"
    assert a.risks == []


def test_job_id_stable() -> None:
    assert job_id_for("repo", "main") == job_id_for("repo", "main")
    assert job_id_for("repo", "main") != job_id_for("repo", "dev")
    assert len(job_id_for("repo", "main")) == 32
