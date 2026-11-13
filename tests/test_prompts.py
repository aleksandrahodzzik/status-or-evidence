from sor.client import count_tokens
from sor.config import ALLOWED_MOAS
from sor.prompts import AUTHORITY, CONDITIONS, condition_name, reviewer_message, turn1_messages, turn2_messages

SNIPS_A = [{"feature": "tub_mean", "value": 25.1}, {"feature": "tub_std", "value": 32.4},
           {"feature": "nuc_form_factor", "value": -23.6}]
SNIPS_B = [{"feature": "cell_area", "value": -4.0}, {"feature": "act_mean", "value": 6.0},
           {"feature": "nuc_dna_mean", "value": -8.7}]


def tokens(text: str) -> int:
    return count_tokens([{"role": "user", "content": text}])


ATLAS = {"target_sim": 0.76, "answer_sim": 0.43}


def test_thirteen_conditions():
    assert len(CONDITIONS) == 13 and CONDITIONS[0] == "control"
    assert "auth-high_ev-evidence_dir-correct" in CONDITIONS and "auth-low_ev-bare_dir-misleading" in CONDITIONS
    assert "auth-high_ev-atlas_dir-misleading" in CONDITIONS


def test_atlas_objection_quotes_both_similarities():
    msg = reviewer_message("auth-low_ev-atlas_dir-correct", "Eg5 inhibitors", atlas=ATLAS, answer="DNA damage")
    assert "nearest Eg5 inhibitors reference has cosine similarity 0.76" in msg
    assert "0.43 for the nearest DNA damage reference" in msg
    hi = reviewer_message("auth-high_ev-atlas_dir-correct", "Eg5 inhibitors", atlas=ATLAS, answer="DNA damage")
    assert hi.replace(AUTHORITY["high"], "X") == msg.replace(AUTHORITY["low"], "X")


def test_turn1_lists_all_moas_and_format():
    user = turn1_messages("EVIDENCE")[1]["content"]
    assert all(m in user for m in ALLOWED_MOAS)
    assert '"moa"' in user and '"confidence"' in user and "60 words" in user


def test_control_has_no_alternative():
    msg = reviewer_message("control")
    assert "double-check" in msg
    body = msg.split("Give your answer again.")[0]
    assert not any(m in body for m in ALLOWED_MOAS)


def test_every_objection_names_target():
    for cond in CONDITIONS[1:]:
        snips = SNIPS_A if "ev-evidence" in cond else None
        assert "Eg5 inhibitors" in reviewer_message(cond, "Eg5 inhibitors", snips, ATLAS, "DNA damage")


def test_authority_length_within_10_percent():
    for ev in ("evidence", "bare"):
        for d in ("correct", "misleading"):
            for target in ALLOWED_MOAS:
                snips = SNIPS_A if ev == "evidence" else None
                hi = tokens(reviewer_message(condition_name("high", ev, d), target, snips))
                lo = tokens(reviewer_message(condition_name("low", ev, d), target, snips))
                assert abs(hi - lo) / max(hi, lo) <= 0.10, (ev, d, target, hi, lo)


def test_authority_is_the_only_difference():
    hi = reviewer_message("auth-high_ev-evidence_dir-correct", "DNA damage", SNIPS_A)
    lo = reviewer_message("auth-low_ev-evidence_dir-correct", "DNA damage", SNIPS_A)
    assert hi.replace(AUTHORITY["high"], "X") == lo.replace(AUTHORITY["low"], "X")


def test_correct_and_misleading_share_template():
    """Same template, k and length: only target and quoted features differ."""
    c = reviewer_message("auth-high_ev-evidence_dir-correct", "DNA damage", SNIPS_A)
    m = reviewer_message("auth-high_ev-evidence_dir-misleading", "Epithelial", SNIPS_B)
    strip = lambda s, t, sn: _strip(s.replace(t, "T"), sn)  # noqa: E731
    assert strip(c, "DNA damage", SNIPS_A) == strip(m, "Epithelial", SNIPS_B)
    for ev in ("evidence", "bare"):
        a = reviewer_message(condition_name("low", ev, "correct"), "DNA damage", SNIPS_A if ev == "evidence" else None)
        b = reviewer_message(condition_name("low", ev, "misleading"), "DNA damage",
                             SNIPS_A if ev == "evidence" else None)
        assert a == b


def _strip(text, snips):
    for s in snips:
        text = text.replace(s["feature"], "F").replace(f"{s['value']:+.1f}", "V")
    return text


def test_turn2_carries_actual_turn1_answer():
    t1 = turn1_messages("EV")
    msgs = turn2_messages(t1, "RAW ANSWER", reviewer_message("control"))
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[2]["content"] == "RAW ANSWER" and msgs[:2] == t1
