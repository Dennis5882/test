from pathlib import Path

import pytest

from scripts.auto_codify import (
    PipelineError,
    collect_reference_files,
    normalize_source_rel_path,
    parse_json_response,
)


def test_collect_reference_files_uses_explicit_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    references = tmp_path / "references"
    references.mkdir()
    selected = references / "changed.txt"
    selected.write_text("selected", encoding="utf-8")
    ignored = references / "ignored.txt"
    ignored.write_text("ignored", encoding="utf-8")

    monkeypatch.setenv("REFERENCE_FILES", "references/changed.txt")
    monkeypatch.delenv("REFERENCE_PATTERNS", raising=False)

    files = collect_reference_files()

    assert files == [selected.resolve()]


def test_collect_reference_files_rejects_non_reference_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "references").mkdir()
    (tmp_path / "outside.txt").write_text("x", encoding="utf-8")

    monkeypatch.setenv("REFERENCE_FILES", "outside.txt")

    with pytest.raises(PipelineError):
        collect_reference_files()


def test_collect_reference_files_falls_back_to_patterns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    references = tmp_path / "references"
    references.mkdir()
    included = references / "note.txt"
    included.write_text("hello", encoding="utf-8")
    excluded = references / "diagram.pdf"
    excluded.write_text("pdf placeholder", encoding="utf-8")

    monkeypatch.delenv("REFERENCE_FILES", raising=False)
    monkeypatch.setenv("REFERENCE_PATTERNS", "*.txt")

    files = collect_reference_files()

    assert files == [included.resolve()]
    assert excluded.resolve() not in files


def test_parse_json_response_accepts_fenced_json() -> None:
    payload = parse_json_response(
        '```json\n{"manual_markdown": "ok", "source_files": []}\n```',
        "test",
    )

    assert payload["manual_markdown"] == "ok"


def test_parse_json_response_extracts_json_object_from_text() -> None:
    payload = parse_json_response(
        'Here is the result:\n{"chunk_label": "chunk_1", "clauses": []}\nThanks.',
        "test",
    )

    assert payload["chunk_label"] == "chunk_1"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("/src/smoke_trigger.py", "smoke_trigger.py"),
        ("src/wind_load.py", "wind_load.py"),
        ("wind_load.py", "wind_load.py"),
        ("/src/loads/wind.py", "loads/wind.py"),
        ("src\\loads\\wind.py", "loads/wind.py"),
    ],
)
def test_normalize_source_rel_path_strips_prefixes(raw: str, expected: str) -> None:
    assert normalize_source_rel_path(raw).as_posix() == expected


@pytest.mark.parametrize("bad", ["../escape.py", "src/../../escape.py", "notes.txt", "  "])
def test_normalize_source_rel_path_rejects_invalid(bad: str) -> None:
    with pytest.raises(PipelineError):
        normalize_source_rel_path(bad)
