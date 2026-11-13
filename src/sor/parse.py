"""Model answer -> {moa, confidence, rationale, parse_status}.

Order: strict JSON of the whole text -> first balanced {...} block that parses -> give up. The moa string is
normalised against ALLOWED_MOAS (case, whitespace, hyphens, and the explicit synonym map below). confidence must be
an integer 0-100 (85, 85.0, "85" and "85%" accepted). Anything else: parse_status="unparsed"; the record is kept
and counted separately, never guessed.
"""

from __future__ import annotations

import json
import re

from sor.config import ALLOWED_MOAS


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", s.strip().lower()).strip(" .")


# explicit synonyms (normalised form -> canonical class); singular/plural and British spellings only
SYNONYMS = {
    "actin disruptor": "Actin disruptors",
    "aurora kinase inhibitor": "Aurora kinase inhibitors",
    "cholesterol lowering agent": "Cholesterol-lowering",
    "cholesterol lowering agents": "Cholesterol-lowering",
    "eg5 inhibitor": "Eg5 inhibitors",
    "kinase inhibitor": "Kinase inhibitors",
    "microtubule destabiliser": "Microtubule destabilizers",
    "microtubule destabilisers": "Microtubule destabilizers",
    "microtubule destabilizer": "Microtubule destabilizers",
    "microtubule stabiliser": "Microtubule stabilizers",
    "microtubule stabilisers": "Microtubule stabilizers",
    "microtubule stabilizer": "Microtubule stabilizers",
}
_CANON = {_norm(m): m for m in ALLOWED_MOAS} | {_norm(k): v for k, v in SYNONYMS.items()}


def normalize_moa(value) -> str | None:
    if not isinstance(value, str):
        return None
    return _CANON.get(_norm(value))


def _confidence(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and float(value).is_integer() and 0 <= value <= 100:
        return int(value)
    return None


def _first_json_object(text: str) -> dict | None:
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        depth, in_str, esc = 0, False, False
        for j in range(start, len(text)):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:j + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
    return None


def parse_answer(text: str | None) -> dict:
    out = {"moa": None, "confidence": None, "rationale": None, "parse_status": "unparsed"}
    if not text or not text.strip():
        return out
    obj, how = None, None
    try:
        obj = json.loads(text.strip())
        how = "ok" if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    if not isinstance(obj, dict):
        obj, how = _first_json_object(text), "fallback"
    if not isinstance(obj, dict):
        return out
    moa, conf = normalize_moa(obj.get("moa")), _confidence(obj.get("confidence"))
    if moa is None or conf is None:
        return out
    rationale = obj.get("rationale")
    return {"moa": moa, "confidence": conf, "rationale": rationale if isinstance(rationale, str) else None,
            "parse_status": how}
