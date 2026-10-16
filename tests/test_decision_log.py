"""ASSUMPTIONS.md, the decision log and everything that cites an entry stay in step.

The log keeps every entry under a stable ID that the code, the tests and the other docs cite, and
ASSUMPTIONS.md links each ID it mentions to that entry's heading. These fail when an ID repeats or goes
missing, when something cites an ID that has no entry, or when a link points at a heading the log doesn't
have.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs/DECISION_LOG.md"
SUMMARY = ROOT / "ASSUMPTIONS.md"
DOCS = [ROOT / "README.md", SUMMARY, LOG, ROOT / "docs/CANONICAL_MODEL.md", ROOT / "docs/FIELD_COVERAGE.md"]
CODE = [ROOT / folder for folder in ("src", "tests", "scripts", "mappings")]
CITED = re.compile(r"\bA-\d{2}\b")
ENTRY = re.compile(r"^### (A-\d{2}) .+$", re.M)


def anchor(heading: str) -> str:
    """The anchor GitHub gives a heading: lowercased, punctuation dropped, each space a hyphen."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def _entries() -> dict[str, str]:
    """Each entry's ID, with the anchor of its heading."""
    text = LOG.read_text(encoding="utf-8")
    return {m.group(1): anchor(m.group(0).removeprefix("### ")) for m in ENTRY.finditer(text)}


def test_entry_ids_run_from_a_01_without_gaps_or_repeats():
    ids = ENTRY.findall(LOG.read_text(encoding="utf-8"))
    assert sorted(ids) == [f"A-{n:02d}" for n in range(1, len(ids) + 1)], ids


def test_every_cited_id_has_an_entry():
    entries = _entries()
    files = [*DOCS, *(path for folder in CODE for path in folder.rglob("*") if path.suffix in (".py", ".json", ".md"))]
    unknown = sorted(
        f"{path.relative_to(ROOT)}: {cited}"
        for path in files
        for cited in set(CITED.findall(path.read_text(encoding="utf-8")))
        if cited not in entries
    )
    assert not unknown, unknown


def test_links_into_the_log_reach_a_heading():
    headings = {anchor(text) for text in re.findall(r"^#{1,6} (.+)$", LOG.read_text(encoding="utf-8"), re.M)}
    broken = sorted(
        f"{path.relative_to(ROOT)}: {target}"
        for path in DOCS
        for target in re.findall(r"DECISION_LOG\.md#([\w-]+)", path.read_text(encoding="utf-8"))
        if target not in headings
    )
    assert not broken, broken


def test_the_summary_links_each_id_to_its_own_entry():
    text = SUMMARY.read_text(encoding="utf-8")
    targets = dict(re.findall(r"^\[(A-\d{2})\]: docs/DECISION_LOG\.md#([\w-]+)$", text, re.M))
    used = set(re.findall(r"\[(A-\d{2})\](?!:)", text))
    assert used == set(targets), sorted(used ^ set(targets))
    entries = _entries()
    assert not [cited for cited, target in targets.items() if entries.get(cited) != target]
