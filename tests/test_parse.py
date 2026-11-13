import pytest

from sor.parse import normalize_moa, parse_answer


def test_strict_json():
    r = parse_answer('{"moa": "DNA damage", "confidence": 80, "rationale": "x"}')
    assert r == {"moa": "DNA damage", "confidence": 80, "rationale": "x", "parse_status": "ok"}


@pytest.mark.parametrize("text", [
    '```json\n{"moa": "DNA damage", "confidence": 80, "rationale": "x"}\n```',
    'Here is my answer: {"moa": "DNA damage", "confidence": 80, "rationale": "has {braces} inside"} done',
    'not json {broken} then {"moa": "DNA damage", "confidence": 80, "rationale": "x"}',
])
def test_fallback_first_block(text):
    r = parse_answer(text)
    assert r["moa"] == "DNA damage" and r["confidence"] == 80 and r["parse_status"] == "fallback"


@pytest.mark.parametrize("raw,canon", [
    ("microtubule  STABILIZERS", "Microtubule stabilizers"),
    (" Eg5 inhibitors ", "Eg5 inhibitors"),
    ("cholesterol lowering", "Cholesterol-lowering"),
    ("Microtubule stabiliser", "Microtubule stabilizers"),
    ("microtubule-destabilisers", "Microtubule destabilizers"),
    ("Kinase inhibitor", "Kinase inhibitors"),
    ("dna_replication", "DNA replication"),
])
def test_normalize(raw, canon):
    assert normalize_moa(raw) == canon


@pytest.mark.parametrize("raw", ["Tubulin binder", "unknown", "", None, 3, "Microtubule"])
def test_normalize_rejects(raw):
    assert normalize_moa(raw) is None


@pytest.mark.parametrize("conf,expected", [(85, 85), (85.0, 85), ("85", 85), ("85%", 85), (0, 0), (100, 100)])
def test_confidence_accepted(conf, expected):
    import json
    r = parse_answer(json.dumps({"moa": "Epithelial", "confidence": conf, "rationale": "r"}))
    assert r["confidence"] == expected and r["parse_status"] == "ok"


@pytest.mark.parametrize("conf", [0.85, 150, -1, "high", True, None])
def test_confidence_rejected(conf):
    import json
    r = parse_answer(json.dumps({"moa": "Epithelial", "confidence": conf, "rationale": "r"}))
    assert r["parse_status"] == "unparsed" and r["moa"] is None


@pytest.mark.parametrize("text", ["", None, "   ", "I think DNA damage, 80%", "[1, 2]",
                                  '{"moa": "Tubulin binder", "confidence": 50}', '{"confidence": 50}'])
def test_unparsed_never_guessed(text):
    r = parse_answer(text)
    assert r == {"moa": None, "confidence": None, "rationale": None, "parse_status": "unparsed"}
