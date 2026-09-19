"""Fill the eval corpus with prose, once, and freeze it.

`tests/ai/evalcorpus/shape.py` holds the facts a benchmark question can be asked
about — statuses, priorities, owners, ages. This script writes the other half:
the subjects, bodies and names that make those rows read like a real workspace
instead of `Ticket 4`.

**The split is the point.** A model writes only text nothing is graded on. It
never invents a status, a slug, an owner or a count, because the oracle derives
each case's expected answer by filtering the shape — so prose that could change a
filter's result would change the ground truth every time this script ran.

**And then it is frozen.** The output is committed. Regenerating needs
``--refresh``; a bare run only checks. Two reasons. A benchmark whose corpus
moves underneath it cannot be compared across runs, which is most of what a
benchmark is for. And a committed file is one a person can read in a diff, which
matters for text a model wrote.

Staleness is keyed on the *prompt inputs*, not the file: `--check` recomputes
what this script would send to the model and compares it with the fingerprint in
`_meta`. Editing a comment in `shape.py` does not invalidate anything; adding a
ticket, or changing the request type the subject is supposed to describe, does.

    # Is the committed corpus still the one this shape asks for?
    python scripts/generate_eval_corpus.py --check

    # Rewrite it (needs a model — LM Studio on :1234 by default)
    python scripts/generate_eval_corpus.py --refresh

    # Somewhere else, or a different model
    python scripts/generate_eval_corpus.py --refresh \
        --base-url http://localhost:1234/v1 --model qwen/qwen3.5-9b
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.ai.evalcorpus import shape

DEFAULT_OUT = (
    Path(__file__).parent.parent / "tests" / "ai" / "evalcorpus" / "data" / "prose.json"
)
DEFAULT_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3.5-9b")


# ---------------------------------------------------------------------------
# What the model is asked for
# ---------------------------------------------------------------------------
#
# Each entry names a section of the corpus, the fields the model fills, and the
# shape fields it is shown so the text matches the facts. Anything not listed
# under `shown` is invisible to the model, which is the cheapest way to stop
# prose encoding something the oracle has not been told about.

SECTIONS: dict[str, dict[str, Any]] = {
    "people": {
        "rows": lambda: shape.PEOPLE,
        "shown": ("slug", "function"),
        "fields": ("name",),
        "instruction": (
            "Invent a plausible full name for a colleague at a software company. "
            "Vary the origins of the names. Do not use the name of anyone famous."
        ),
    },
    "accounts": {
        "rows": lambda: shape.ACCOUNTS,
        "shown": ("slug",),
        "fields": ("name", "domain"),
        "instruction": (
            "Turn the slug into a company name, and give it a domain. The domain "
            "MUST end in .example.com — these are fictional customers and must "
            "never resemble a real company's address."
        ),
    },
    "tickets": {
        "rows": lambda: shape.TICKETS,
        "shown": ("slug", "request_type", "priority", "severity"),
        "fields": ("subject", "body"),
        "instruction": (
            "Write a support ticket. `subject` is one line as a customer would "
            "type it. `body` is two or three sentences describing the problem. "
            "Match the request type and severity you are given. Do NOT mention "
            "the status, who it is assigned to, how old it is, or any ticket "
            "number — none of that belongs in the text."
        ),
    },
    "sprints": {
        "rows": lambda: shape.SPRINTS,
        "shown": ("slug",),
        "fields": ("name",),
        "instruction": "Turn the slug into a short sprint name, title case.",
    },
    "tasks": {
        "rows": lambda: shape.TASKS,
        "shown": ("slug", "priority"),
        "fields": ("title", "description"),
        "instruction": (
            "Write an engineering task. `title` is an imperative one-liner. "
            "`description` is one or two sentences. Do not mention status, "
            "assignee or estimate."
        ),
    },
    "blockers": {
        "rows": lambda: shape.BLOCKERS,
        "shown": ("slug", "severity"),
        "fields": ("summary",),
        "instruction": (
            "One sentence describing what is blocking the team and why it is stuck."
        ),
    },
}


def build_prompt_inputs() -> dict[str, list[dict[str, Any]]]:
    """Exactly what the model will be shown, per section.

    This is also the staleness key: if what we would send changes, the committed
    text no longer answers the question it was generated for.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for name, spec in SECTIONS.items():
        rows = []
        for row in spec["rows"]():
            rows.append({key: getattr(row, key, None) for key in spec["shown"]})
        out[name] = rows
    return out


def shape_fingerprint(inputs: dict[str, list[dict[str, Any]]] | None = None) -> str:
    if inputs is None:
        inputs = build_prompt_inputs()
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
#
# `seed_service_desk.py` exists because an earlier script shipped one real
# customer's staff names, email addresses and lines of business to everybody who
# cloned the repo. A model writing the text makes that easier to do by accident,
# not harder, so the output is checked before it is written.

ALLOWED_DOMAIN_SUFFIXES = (".example.com", ".example.org", ".example", "example.com")

# Names that must never appear. Extend it when a real customer or colleague
# turns up in generated text — the check is only as good as the list.
DENYLIST = ("bimaplan", "northwind.example")

_EMAIL_OR_DOMAIN = re.compile(
    r"\b[a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|co|dev|ai|in|uk)\b", re.IGNORECASE
)


def validate_prose(data: dict[str, Any]) -> list[str]:
    """Problems with generated text, as a list of human-readable strings."""
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "_meta":
                    continue
                walk(value, f"{path}.{key}" if path else key)
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
            return
        if not isinstance(node, str):
            return

        lowered = node.lower()
        for banned in DENYLIST:
            if banned in lowered:
                problems.append(f"{path}: contains {banned!r}")
        for match in _EMAIL_OR_DOMAIN.findall(node):
            if not match.lower().endswith(ALLOWED_DOMAIN_SUFFIXES):
                problems.append(f"{path}: domain {match!r} is not a reserved example domain")

    walk(data, "")
    return problems


def validate_coverage(data: dict[str, Any]) -> list[str]:
    """Every row has the fields its section promised, and nothing is blank."""
    problems: list[str] = []
    for name, spec in SECTIONS.items():
        section = data.get(name)
        if not isinstance(section, dict):
            problems.append(f"{name}: missing")
            continue
        for row in spec["rows"]():
            entry = section.get(row.slug)
            if not isinstance(entry, dict):
                problems.append(f"{name}.{row.slug}: missing")
                continue
            for field_name in spec["fields"]:
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    problems.append(f"{name}.{row.slug}.{field_name}: empty")
        extra = set(section) - {row.slug for row in spec["rows"]()}
        if extra:
            problems.append(f"{name}: unknown slugs {sorted(extra)}")
    return problems


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def section_prompt(name: str, spec: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    fields = ", ".join(f"`{f}`" for f in spec["fields"])
    return (
        f"{spec['instruction']}\n\n"
        f"Everything you write is fictional and will be committed to a public "
        f"repository as test data. Never use a real person's or company's name.\n\n"
        f"Below are {len(rows)} rows. For each one, produce {fields}.\n"
        f"Answer with JSON only: an object keyed by `slug`, each value an object "
        f"with exactly the keys {list(spec['fields'])}. No prose outside the JSON.\n\n"
        f"{json.dumps(rows, indent=2)}"
    )


def _extract_json(text: str) -> dict[str, Any]:
    """Models fence their JSON, or preface it. Take the outermost object."""
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def call_model(base_url: str, model: str, prompt: str, timeout: float) -> str:
    import httpx

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LMSTUDIO_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json={
            "model": model,
            # Zero because the value of a frozen corpus is that it is the same
            # one next time somebody regenerates it after a small shape edit.
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# A local model is the documented default and a large one is slow — 16 seconds
# for a trivial reply on the machine this was written against, and a reasoning
# model spends most of its budget before it writes anything. Asking for sixteen
# ticket bodies in one request is a single point of failure worth minutes of
# wall clock; asking in small batches costs the same tokens and loses at most
# one batch when something goes wrong.
BATCH_SIZE = 4


def generate(base_url: str, model: str, timeout: float) -> dict[str, Any]:
    inputs = build_prompt_inputs()
    data: dict[str, Any] = {}
    for name, spec in SECTIONS.items():
        rows = inputs[name]
        section: dict[str, Any] = {}
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            print(
                f"  {name}: {start + len(batch)}/{len(rows)} …",
                file=sys.stderr,
                flush=True,
            )
            raw = call_model(base_url, model, section_prompt(name, spec, batch), timeout)
            section.update(_extract_json(raw))
        data[name] = section

    data["_meta"] = {
        "generator": "scripts/generate_eval_corpus.py",
        "model": model,
        "base_url": base_url,
        "shape_fingerprint": shape_fingerprint(inputs),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": (
            "Generated prose, frozen on purpose. Facts live in "
            "tests/ai/evalcorpus/shape.py; nothing here is graded. Regenerate "
            "with scripts/generate_eval_corpus.py --refresh."
        ),
    }
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def check(path: Path) -> int:
    data = load(path)
    if data is None:
        print(
            f"{path} does not exist — run "
            f"`python scripts/generate_eval_corpus.py --refresh`.",
            file=sys.stderr,
        )
        return 1

    committed = data.get("_meta", {}).get("shape_fingerprint")
    current = shape_fingerprint()
    if committed != current:
        print(
            f"{path} is stale: shape.py no longer matches the text that was "
            f"generated for it.\n  committed {committed}\n  current   {current}\n"
            f"Re-run `python scripts/generate_eval_corpus.py --refresh` and commit.",
            file=sys.stderr,
        )
        return 1

    problems = validate_coverage(data) + validate_prose(data)
    if problems:
        print(f"{path} has {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"{path} is current.", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="call a model and rewrite the corpus (default is to check only)",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="'-' for stdout")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    if not args.refresh:
        return check(DEFAULT_OUT if args.out == "-" else Path(args.out))

    print(f"Generating from {args.model} at {args.base_url}", file=sys.stderr)
    try:
        data = generate(args.base_url, args.model, args.timeout)
    except Exception as exc:
        import httpx

        if isinstance(exc, httpx.ReadTimeout):
            print(
                f"\n{args.model!r} did not finish within {args.timeout:.0f}s.\n"
                f"A large local model is slow — raise --timeout, or load a "
                f"smaller model. Progress above shows how far it got.",
                file=sys.stderr,
            )
        elif isinstance(exc, httpx.ConnectError):
            print(
                f"\nNothing is listening at {args.base_url}.\n"
                f"Start LM Studio and load a model, or point --base-url at "
                f"another OpenAI-compatible server.",
                file=sys.stderr,
            )
        elif isinstance(exc, httpx.HTTPStatusError):
            print(
                f"\n{args.base_url} answered {exc.response.status_code}. "
                f"Is {args.model!r} loaded? `curl {args.base_url}/models` lists "
                f"what the server has.",
                file=sys.stderr,
            )
        elif isinstance(exc, (ValueError, KeyError)):
            print(
                f"\n{args.model!r} did not return usable JSON: {exc}\n"
                f"Smaller models often need a second attempt, or a larger one.",
                file=sys.stderr,
            )
        else:
            raise
        return 1

    problems = validate_coverage(data) + validate_prose(data)
    if problems:
        print(f"Refusing to write — {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        return 1

    rendered = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out == "-":
        sys.stdout.write(rendered)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        print(f"Wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
