import copy
import json
from pathlib import Path

import pytest

from conftest import FakeTransport, make_body
from sor.budget import BudgetExceeded
from sor.client import MissingKey, ParamUnsupported, http_transport

MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "evidence"}]
MODEL = "muse-spark-1.3-contributor"


def ledger_lines(cfg):
    p = Path(cfg["paths"]["ledger"])
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def test_cache_hit_is_free_and_leaves_ledger(cfg, client_factory):
    fake = FakeTransport()
    client = client_factory(fake)
    r1 = client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert not r1.cached and r1.cost_usd > 0 and len(ledger_lines(cfg)) == 1
    before = client.budget.total()
    r2 = client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert r2.cached and r2.cost_usd == 0 and r2.text == r1.text
    assert len(fake.calls) == 1 and len(ledger_lines(cfg)) == 1 and client.budget.total() == before
    assert r2.original_cost_usd == r1.cost_usd


def test_cost_from_usage(cfg, client_factory):
    client = client_factory(FakeTransport())
    r = client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert r.cost_usd == pytest.approx(1000 * 0.10 / 1e6 + 500 * 0.20 / 1e6)  # reasoning is inside output
    assert r.reasoning_tokens == 400


def test_seed_and_temperature_in_cache_key(cfg, client_factory):
    fake = FakeTransport()
    client = client_factory(fake)
    client.call_model(MSGS, 0, 0.7, MODEL, "t")
    client.call_model(MSGS, 1, 0.7, MODEL, "t")
    client.call_model(MSGS, 0, 0.3, MODEL, "t")
    assert len(fake.calls) == 3
    assert fake.calls[0]["seed"] == 0 and fake.calls[0]["temperature"] == 0.7


def test_seed_not_sent_but_still_keyed(cfg, client_factory):
    c2 = copy.deepcopy(cfg)
    c2["send_seed"] = False
    fake = FakeTransport()
    client = client_factory(fake, c2)
    client.call_model(MSGS, 0, 0.7, MODEL, "t")
    client.call_model(MSGS, 1, 0.7, MODEL, "t")
    assert "seed" not in fake.calls[0] and len(fake.calls) == 2


def test_kill_switch_fires_before_call(cfg, client_factory):
    c2 = copy.deepcopy(cfg)
    c2["models"]["primary"]["price_out_per_m"] = 1e6  # 8000 max tokens -> $8000 per call
    fake = FakeTransport()
    client = client_factory(fake, c2)
    with pytest.raises(BudgetExceeded):
        client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert fake.calls == [] and ledger_lines(c2) == [] and client.budget.reserved == 0


def test_kill_switch_counts_existing_ledger(cfg, client_factory):
    p = Path(cfg["paths"]["ledger"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"cost_usd": cfg["budget_cap_usd"] - 0.0001}) + "\n", encoding="utf-8")
    fake = FakeTransport()
    with pytest.raises(BudgetExceeded):
        client_factory(fake).call_model(MSGS, 0, 0.7, MODEL, "t")
    assert fake.calls == []


def test_retry_then_success(cfg, client_factory):
    fake = FakeTransport(script=[(429, {"error": "rate"}), (503, {"error": "busy"}),
                                 (200, make_body('{"moa": "DNA damage", "confidence": 5, "rationale": ""}'))])
    r = client_factory(fake).call_model(MSGS, 0, 0.7, MODEL, "t")
    assert r.status == "ok" and r.attempts == 3 and len(ledger_lines(cfg)) == 1


def test_failure_logged_not_dropped_not_cached(cfg, client_factory):
    fake = FakeTransport(script=[(500, {"error": "x"})] * 5)
    client = client_factory(fake)
    r = client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert r.status == "error" and r.attempts == 5 and len(fake.calls) == 5  # 1 + max_retries(4)
    line = json.loads(ledger_lines(cfg)[0])
    assert line["status"] == "error" and line["cost_usd"] == 0
    assert client.peek(MODEL, MSGS, 0.7, 0) is None


def test_non_retryable_error(cfg, client_factory):
    fake = FakeTransport(script=[(401, {"error": "bad key"})])
    r = client_factory(fake).call_model(MSGS, 0, 0.7, MODEL, "t")
    assert r.status == "error" and len(fake.calls) == 1


def test_seed_rejected_stops(cfg, client_factory):
    fake = FakeTransport(script=[(400, {"error": {"message": "Unrecognized request argument: seed"}})])
    client = client_factory(fake)
    with pytest.raises(ParamUnsupported):
        client.call_model(MSGS, 0, 0.7, MODEL, "t")
    assert client.budget.reserved == 0


def test_unpriced_model_refused(cfg, client_factory):
    with pytest.raises(KeyError):
        client_factory(FakeTransport()).call_model(MSGS, 0, 0.7, "muse-wonder-1.0", "t")


def test_missing_key(cfg, monkeypatch):
    monkeypatch.delenv(cfg["api_key_env"], raising=False)
    with pytest.raises(MissingKey):
        http_transport(cfg)({"model": MODEL, "messages": MSGS})


def test_key_never_written(cfg, client_factory, monkeypatch, tmp_path):
    monkeypatch.setenv(cfg["api_key_env"], "sk-SECRET-123")
    client_factory(FakeTransport()).call_model(MSGS, 0, 0.7, MODEL, "t")
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert "sk-SECRET-123" not in p.read_text(encoding="utf-8", errors="ignore")
