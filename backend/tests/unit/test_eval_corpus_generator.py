"""The generator's judgement, tested without a model.

Everything here is the part that decides *what to ask for*, *whether the
committed answer is still valid*, and *whether it is safe to commit*. The model
call itself is one function and is not exercised — what matters is that a bad
answer cannot be written to disk, and that a shape edit cannot go unnoticed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from generate_eval_corpus import (
    SECTIONS,
    _extract_json,
    build_prompt_inputs,
    section_prompt,
    shape_fingerprint,
    validate_coverage,
    validate_prose,
)

from tests.ai.evalcorpus import shape


def _good_corpus() -> dict:
    """A corpus that should pass every check."""
    data = {}
    for name, spec in SECTIONS.items():
        data[name] = {
            row.slug: {field: f"text for {row.slug}" for field in spec["fields"]}
            for row in spec["rows"]()
        }
    data["accounts"] = {
        row.slug: {"name": "Acme Widgets", "domain": "acme.example.com"}
        for row in shape.ACCOUNTS
    }
    data["_meta"] = {"shape_fingerprint": shape_fingerprint()}
    return data


# ─── what gets asked for ───────────────────────────────────────────────


def test_every_row_in_the_shape_is_asked_about():
    inputs = build_prompt_inputs()
    for name, spec in SECTIONS.items():
        assert len(inputs[name]) == len(list(spec["rows"]())), name


def test_the_model_is_never_shown_a_field_the_oracle_grades():
    """Prose must not be able to encode a status, an owner or an age.

    If the model can see them it will write them into the text, and an answer
    could then be graded correct from the ticket body alone — which measures
    nothing about whether the model used the tool.
    """
    graded = {"status", "assignee", "age_days", "needs_triage", "pending_with", "sprint",
              "story_points", "reported_days_ago", "starts_days_ago", "ends_days_ahead", "role"}
    for name, spec in SECTIONS.items():
        assert not (set(spec["shown"]) & graded), (name, spec["shown"])


def test_the_prompt_carries_the_rows_and_the_required_keys():
    prompt = section_prompt("tickets", SECTIONS["tickets"], build_prompt_inputs()["tickets"])
    assert "sd-import-crash" in prompt
    assert "subject" in prompt and "body" in prompt
    assert "fictional" in prompt.lower()


# ─── staleness ─────────────────────────────────────────────────────────


def test_the_fingerprint_is_stable():
    assert shape_fingerprint() == shape_fingerprint()


def test_the_fingerprint_cannot_see_fields_the_model_was_not_shown():
    """Re-statusing a ticket must not invalidate hand-reviewed prose.

    Asserted on the projection rather than by mutating `shape` and re-reading
    it, because `build_prompt_inputs` reads the module directly: a test that
    assigned to a frozen dataclass would prove nothing about the fingerprint.
    """
    inputs = build_prompt_inputs()
    for name, spec in SECTIONS.items():
        for row in inputs[name]:
            assert set(row) == set(spec["shown"]), (name, row)

    ungraded = {"status", "assignee", "age_days", "needs_triage", "pending_with"}
    serialised = json.dumps(inputs)
    for row in shape.TICKETS:
        assert row.slug in serialised
    assert not (ungraded & {key for row in inputs["tickets"] for key in row})


def test_the_fingerprint_moves_when_a_row_is_added():
    inputs = build_prompt_inputs()
    before = shape_fingerprint(inputs)
    inputs["tickets"].append({"slug": "sd-new", "request_type": "bug",
                              "priority": "low", "severity": "low"})
    assert shape_fingerprint(inputs) != before


def test_the_fingerprint_moves_when_a_shown_field_changes():
    inputs = build_prompt_inputs()
    before = shape_fingerprint(inputs)
    inputs["tickets"][0]["request_type"] = "question"
    assert shape_fingerprint(inputs) != before


# ─── coverage ──────────────────────────────────────────────────────────


def test_a_complete_corpus_passes():
    assert validate_coverage(_good_corpus()) == []


def test_a_missing_row_is_reported():
    data = _good_corpus()
    del data["tickets"][shape.TICKETS[0].slug]
    problems = validate_coverage(data)
    assert any(shape.TICKETS[0].slug in p for p in problems)


def test_a_blank_field_is_reported():
    data = _good_corpus()
    data["tickets"][shape.TICKETS[0].slug]["subject"] = "   "
    assert any("subject" in p for p in validate_coverage(data))


def test_a_slug_the_shape_does_not_have_is_reported():
    data = _good_corpus()
    data["tickets"]["sd-invented"] = {"subject": "x", "body": "y"}
    assert any("sd-invented" in p for p in validate_coverage(data))


def test_a_missing_section_is_reported():
    data = _good_corpus()
    del data["blockers"]
    assert any("blockers" in p for p in validate_coverage(data))


# ─── safety ────────────────────────────────────────────────────────────


def test_clean_text_passes():
    assert validate_prose(_good_corpus()) == []


@pytest.mark.parametrize("domain", ["acme.com", "northwind.io", "contoso.co.uk"])
def test_a_domain_outside_the_reserved_range_is_refused(domain):
    data = _good_corpus()
    data["accounts"][shape.ACCOUNTS[0].slug]["domain"] = domain
    assert validate_prose(data), domain


@pytest.mark.parametrize("domain", ["acme.example.com", "widgets.example.org"])
def test_reserved_example_domains_are_allowed(domain):
    data = _good_corpus()
    data["accounts"][shape.ACCOUNTS[0].slug]["domain"] = domain
    assert validate_prose(data) == [], domain


def test_a_denylisted_name_is_refused_wherever_it_appears():
    """The reason `seed_service_desk.py` was rewritten — a real customer's
    names and domains shipped to everyone who cloned the repo."""
    data = _good_corpus()
    data["tickets"][shape.TICKETS[0].slug]["body"] = "Escalated by the Bimaplan ops team."
    assert any("bimaplan" in p for p in validate_prose(data))


def test_the_meta_block_is_not_scanned_for_domains():
    """`_meta` legitimately records a base_url, which is not generated text."""
    data = _good_corpus()
    data["_meta"]["base_url"] = "http://localhost:1234/v1"
    data["_meta"]["model"] = "qwen/qwen3.5-9b"
    assert validate_prose(data) == []


# ─── parsing what a model actually returns ─────────────────────────────


def test_a_fenced_json_block_is_read():
    assert _extract_json('```json\n{"a": {"name": "x"}}\n```') == {"a": {"name": "x"}}


def test_a_preamble_before_the_json_is_ignored():
    assert _extract_json('Sure! Here you go:\n{"a": 1}') == {"a": 1}


def test_output_with_no_json_raises_rather_than_returning_nothing():
    with pytest.raises(ValueError):
        _extract_json("I cannot help with that.")
