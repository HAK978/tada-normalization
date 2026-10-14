"""Suggestions for unmapped values (A-66): proposals for a person to accept, never applied by themselves.

Two local, deterministic methods, used by `python -m normalization review`:

- **arithmetic**: an unknown earning kind decides whether a line is paid in cash. On every paycheck
  the line appears on, test whether the provider's own totals reconcile with it treated as cash or
  as non-cash. This is live arithmetic, the kind of evidence the rules accept, but it only separates
  cash kinds from non-cash kinds; it can't tell MEMO from NON_CASH_FRINGE.
- **similarity**: compare the unknown raw value and label with texts already mapped to the same
  canonical type: the code tables of every provider, the values mapped in the reviewed output, and
  the canonical value names. Similar names are a hint for the reviewer, never evidence (mapping from
  names alone is exactly what the evidence rule forbids). When arithmetic has narrowed the kind,
  similarity only ranks within it.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from importlib import import_module
from typing import Any, cast

from .canonical.codes import NON_CASH_EARNING_KINDS, EarningKind
from .canonical.records import PayStatement
from .canonical.types import Coded
from .checks import TOLERANCE
from .mappings import Unmapped, _field, _key, coded_values, kind_of, value_of
from .output import Output
from .providers import PROVIDERS

CASH_KINDS = (EarningKind.EARNINGS.value, EarningKind.REIMBURSEMENT.value)
NON_CASH_KINDS = tuple(sorted(k.value for k in NON_CASH_EARNING_KINDS))
MIN_SIMILARITY = 0.3
_WORDS = re.compile(r"[a-z]+|\d+")


@dataclass
class Suggestion:
    method: str  # "arithmetic" or "similarity"
    values: list[str]  # candidate canonical values, best first; empty when the evidence contradicts itself
    confidence: float  # 0..1: the share of paychecks that agree, or the similarity score
    reasoning: str


def suggest(items: list[Unmapped], outputs: list[tuple[str, Output]]) -> None:
    """Attach suggestions to each review item that has a canonical type."""
    arithmetic = _arithmetic(outputs)
    kinds = {item.kind for item in items if _is_enum(item.kind)}
    vocabulary = _vocabulary(outputs, kinds)
    for item in items:
        found = arithmetic.get((item.provider, item.field, item.raw))
        if found:
            item.suggestions.append(found)
        if _is_enum(item.kind):
            within = set(found.values) if found and found.values else None
            similar = _similar(item, vocabulary.get(item.kind, []), within)
            if similar:
                item.suggestions.append(similar)


# ---------------------------------------------------------------- arithmetic


def _arithmetic(outputs: list[tuple[str, Output]]) -> dict[tuple[str, str, str], Suggestion]:
    tally: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for provider, output in outputs:
        for statement in cast("list[PayStatement]", output.records["pay_statements"]):
            counted = [line for line in statement.earnings if line.in_gross is not False]
            unknown = {
                (provider, _field(line.kind.source_field), _key(line.kind.raw))
                for line in counted
                if _unmapped(line.kind)
            }
            if len(unknown) != 1:
                for key in unknown:  # several unknown kinds on one paycheck can't be told apart
                    tally[key]["inconclusive"] += 1
                continue
            key = next(iter(unknown))
            tally[key][_test(statement, counted)] += 1
    found = {}
    for key, counts in tally.items():
        cash, non_cash, neither = counts["cash"], counts["non-cash"], counts["neither"]
        tested = cash + non_cash + neither
        skipped = f"; {counts['inconclusive']} paychecks couldn't be tested" if counts["inconclusive"] else ""
        if cash and not non_cash:
            found[key] = Suggestion(
                "arithmetic",
                list(CASH_KINDS),
                round(cash / tested, 3),
                f"net pay reconciles on {cash} of {tested} paychecks only if this line is paid in cash{skipped}",
            )
        elif non_cash and not cash:
            found[key] = Suggestion(
                "arithmetic",
                list(NON_CASH_KINDS),
                round(non_cash / tested, 3),
                f"net pay reconciles on {non_cash} of {tested} paychecks only if this line is not paid out{skipped}",
            )
        elif cash and non_cash:
            found[key] = Suggestion(
                "arithmetic",
                [],
                0.0,
                f"contradictory: reconciles as cash on {cash} paychecks and as non-cash on {non_cash}{skipped}",
            )
    return found


def _test(statement: Any, counted: list) -> str:
    """Which reading of the one unknown line makes this paycheck's own totals add up."""
    totals = statement.totals
    if totals.net_pay is None:
        return "inconclusive"
    unknown = sum((line.amount.amount for line in counted if _unmapped(line.kind)), Decimal(0))
    if unknown == 0:
        return "inconclusive"
    wages = totals.gross_wages.amount if totals.gross_wages else sum((x.amount.amount for x in counted), Decimal(0))
    known_non_cash = sum(
        (
            x.amount.amount
            for x in counted
            if not _unmapped(x.kind) and EarningKind(x.kind.value) in NON_CASH_EARNING_KINDS
        ),
        Decimal(0),
    )
    taxes = sum((t.amount.amount for t in statement.taxes if t.paid_by == "EMPLOYEE"), Decimal(0))
    deductions = sum((d.employee_amount.amount for d in statement.deductions if d.employee_amount), Decimal(0))

    def holds(non_cash: Decimal) -> bool:
        ok = abs(wages - non_cash - taxes - deductions - totals.net_pay.amount) <= TOLERANCE
        if totals.gross_pay is not None and not totals.gross_pay.derived:
            ok = ok and abs(wages - non_cash - totals.gross_pay.amount) <= TOLERANCE
        return ok

    as_cash, as_non_cash = holds(known_non_cash), holds(known_non_cash + unknown)
    if as_cash and not as_non_cash:
        return "cash"
    if as_non_cash and not as_cash:
        return "non-cash"
    return "neither"


# ---------------------------------------------------------------- similarity


def _vocabulary(outputs: list[tuple[str, Output]], kinds: set[type[Enum]]) -> dict[type, list[tuple[str, str, str]]]:
    """Known (text, canonical value, where it comes from) per canonical type."""
    vocabulary: dict[type, list[tuple[str, str, str]]] = defaultdict(list)
    for provider, package in PROVIDERS.items():
        module = import_module(f"normalization.providers.{package}.codes")
        for name, table in vars(module).items():
            if not isinstance(table, dict) or name.startswith("_"):
                continue
            for key, value in table.items():
                member = value[0] if isinstance(value, tuple) and value else value
                text = " ".join(k for k in key if isinstance(k, str)) if isinstance(key, tuple) else key
                if isinstance(member, Enum) and type(member) in kinds and isinstance(text, str) and text.strip():
                    vocabulary[type(member)].append((text, member.value, f"{provider} {name}"))
    for provider, output in outputs:
        for records in output.records.values():
            for record in records:
                for coded in coded_values(record):
                    kind = kind_of(coded)
                    if kind not in kinds or _unmapped(coded):
                        continue
                    for text in (coded.raw, coded.label):
                        if isinstance(text, str) and text.strip():
                            vocabulary[kind].append((text, value_of(coded), f"{provider} {coded.source_field}"))
    for kind in kinds:
        for member in kind:
            if member.value not in ("UNMAPPED", "OTHER"):
                vocabulary[kind].append((member.value.replace("_", " "), member.value, "canonical name"))
    return {kind: list(dict.fromkeys(texts)) for kind, texts in vocabulary.items()}


def _similar(item: Unmapped, known: list[tuple[str, str, str]], within: set[str] | None) -> Suggestion | None:
    texts = [t for t in (item.raw, *item.labels) if t and _WORDS.search(t.lower())]
    candidates = [k for k in known if within is None or k[1] in within]
    if not texts or not candidates:
        return None
    weights = _idf([k[0] for k in candidates])
    best: dict[str, tuple[float, str]] = {}
    for text in texts:
        for known_text, value, _source in candidates:
            score = max(_cosine(text, known_text, weights), _trigram(text, known_text))
            if score > best.get(value, (0.0, ""))[0]:
                best[value] = (score, known_text)
    ranked = sorted(((s, v, t) for v, (s, t) in best.items() if s >= MIN_SIMILARITY), key=lambda x: (-x[0], x[1]))[:3]
    if not ranked:
        return None
    reasons = ", ".join(f"{v} (like {t!r}, {s:.2f})" for s, v, t in ranked)
    scope = " among the kinds arithmetic allows" if within else ""
    return Suggestion(
        "similarity",
        [v for _, v, _ in ranked],
        round(ranked[0][0], 3),
        f"similar names{scope}: {reasons}. A hint only; names are not evidence",
    )


def _idf(texts: list[str]) -> dict[str, float]:
    counts = Counter(word for text in texts for word in set(_WORDS.findall(text.lower())))
    n = len(texts)
    return {word: math.log((n + 1) / (df + 1)) + 1 for word, df in counts.items()} | {"": math.log(n + 1) + 1}


def _cosine(a: str, b: str, weights: dict[str, float]) -> float:
    """Word overlap, with words that are common in the vocabulary counting less."""
    wa, wb = set(_WORDS.findall(a.lower())), set(_WORDS.findall(b.lower()))
    weight = lambda w: weights.get(w, weights[""])  # noqa: E731
    shared = sum(weight(w) ** 2 for w in wa & wb)
    norm = math.sqrt(sum(weight(w) ** 2 for w in wa) * sum(weight(w) ** 2 for w in wb))
    return shared / norm if norm else 0.0


def _trigram(a: str, b: str) -> float:
    """Character overlap, which catches variants like 'Bi-Weekly' and 'BIWEEKLY'."""

    def grams(text: str) -> set[str]:
        s = f" {''.join(_WORDS.findall(text.lower()))} "
        return {s[i : i + 3] for i in range(len(s) - 2)}

    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


# ---------------------------------------------------------------- helpers


def _is_enum(kind: Any) -> bool:
    return isinstance(kind, type) and issubclass(kind, Enum)


def _unmapped(coded: Coded) -> bool:
    return value_of(coded) == "UNMAPPED"
