import re

import pandas as pd
import pytest

from sor.config import ALLOWED_MOAS, VARIANTS
from sor.load import NSC_PATTERN, RAW, Redactor, evidence_text
from sor.prompts import CONDITIONS, parse_condition, reviewer_message, turn1_messages, turn2_messages
from sor.targets import compute_targets, evidence_snippets

ALL_NAMES = pd.read_csv(RAW / "metadata" / "BBBC021_v1_compound.csv").compound.dropna().tolist()
NAME_RE = Redactor(ALL_NAMES).pattern
ID_RE = re.compile(r"\b(?:w_[0-9a-f]{10}|f_[0-9a-f]{12}|s_[0-9a-f]{10}|run_[0-9a-f]{12})\b")


def all_turn2(c, variant):
    """Every turn-2 conversation that can occur for this compound (any turn-1 answer)."""
    t1 = turn1_messages(evidence_text(c, variant))
    for a in ALLOWED_MOAS:
        tg = compute_targets(c, a)
        answer = '{"moa": "%s", "confidence": 60, "rationale": "r"}' % a
        for cond in CONDITIONS:
            p = parse_condition(cond)
            target = None if cond == "control" else (tg["correct_target"] if p["direction"] == "correct"
                                                      else tg["misleading_target"])
            if cond != "control" and target is None:
                continue
            snip = evidence_snippets(c, target) if p["evidence"] == "evidence" else None
            rev = reviewer_message(cond, target, snip)
            yield a, cond, rev, turn2_messages(t1, answer, rev)


def test_compounds_complete(compounds):
    assert len(compounds) == 38
    assert {c["true_moa"] for c in compounds} == set(ALLOWED_MOAS)


@pytest.mark.parametrize("variant", VARIANTS)
def test_no_compound_name_or_ids_in_turn1(compounds, variant):
    for c in compounds:
        text = "\n".join(m["content"] for m in turn1_messages(evidence_text(c, variant)))
        assert c["compound_name"].lower() not in text.lower(), c["compound_id"]
        assert not NAME_RE.search(text), (c["compound_id"], NAME_RE.search(text))
        assert not ID_RE.search(text), (c["compound_id"], ID_RE.search(text))


def test_no_compound_name_in_any_turn2(compounds):
    for c in compounds:
        for _, cond, rev, msgs in all_turn2(c, "with_nsc"):
            assert not NAME_RE.search(rev), (c["compound_id"], cond)
            assert c["compound_name"].lower() not in msgs[-1]["content"].lower()


def test_truth_absent_from_misleading_objections(compounds):
    """The reviewer message we write never contains the true MoA string in a misleading cell (the shared turn-1
    part lists all 12 classes, so the check is on the reviewer message)."""
    n = 0
    for c in compounds:
        for v in VARIANTS:
            for a, cond, rev, _ in all_turn2(c, v):
                if parse_condition(cond)["direction"] == "misleading":
                    n += 1
                    assert c["true_moa"] not in rev, (c["compound_id"], a, cond)
    assert n > 0


def test_no_nsc_variant_has_no_atlas_text(compounds):
    for c in compounds:
        no = evidence_text(c, "no_nsc")
        assert not NSC_PATTERN.search(no), (c["compound_id"], NSC_PATTERN.search(no))
        assert NSC_PATTERN.search(evidence_text(c, "with_nsc"))  # sanity: the with_nsc variant does carry it


def test_no_nsc_is_with_nsc_minus_atlas(compounds):
    for c in compounds:
        kept = [b["text"] for b in c["evidence_blocks"] if b["kind"] != "atlas"]
        assert all(t in evidence_text(c, "no_nsc") for t in kept)
        assert all(b["variants"] == ["with_nsc"] for b in c["evidence_blocks"] if b["kind"] == "atlas")
