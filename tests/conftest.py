import copy
import json
from pathlib import Path

import pytest
import yaml

from sor.budget import Budget
from sor.client import ModelClient
from sor.config import ROOT, load_config


def make_body(content: str, prompt_tokens: int = 1000, completion_tokens: int = 500, reasoning: int = 400) -> dict:
    return {"choices": [{"message": {"content": content, "reasoning_content": "thinking..."},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}


class FakeTransport:
    """Stands in for the HTTP API. Turn 1 answers `turn1_moa` (or a per-compound answer via `answers`);
    turn 2 follows the reviewer's target in objection conditions and keeps the answer in the control."""

    def __init__(self, turn1_moa: str = "Microtubule stabilizers", script: list | None = None):
        self.turn1_moa = turn1_moa
        self.script = list(script or [])  # optional queue of (status, body) overriding the default
        self.calls: list[dict] = []

    def __call__(self, payload: dict):
        self.calls.append(payload)
        if self.script:
            status, body = self.script.pop(0)
            return status, body, {}
        msgs = payload["messages"]
        if len(msgs) == 2:
            moa = self.turn1_moa
        else:
            last = msgs[-1]["content"]
            moa = json.loads(msgs[2]["content"])["moa"]
            marker = "I think the MoA is "
            if marker in last:
                moa = last.split(marker, 1)[1].split(". ", 1)[0]
        return 200, make_body(json.dumps({"moa": moa, "confidence": 70, "rationale": "fake"})), {}


@pytest.fixture
def cfg(tmp_path: Path) -> dict:
    c = copy.deepcopy(load_config())
    c["paths"] = {**c["paths"], "cache": str(tmp_path / "cache"), "ledger": str(tmp_path / "budget" / "ledger.jsonl"),
                  "runs": str(tmp_path / "runs")}
    c["concurrency"] = 4
    return c


@pytest.fixture
def cfg_file(cfg: dict, tmp_path: Path) -> str:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(p)


@pytest.fixture
def client_factory(cfg: dict):
    def make(transport, config=None):
        c = config or cfg
        budget = Budget(Path(c["paths"]["ledger"]), c["budget_cap_usd"], c["hard_limit_usd"])
        return ModelClient(c, budget, Path(c["paths"]["cache"]), transport=transport, sleep=lambda s: None)
    return make


@pytest.fixture(scope="session")
def compounds():
    from sor.load import load_compounds
    return load_compounds(ROOT / "data" / "compounds.jsonl")
