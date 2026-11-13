"""CLI for the experiment.

    python -m sor.run estimate                      # $0: cost estimates for every command and both models
    python -m sor.run probe   [--model M] [--yes]   # 1 tiny call: does the API accept seed + temperature?
    python -m sor.run pilot   [--model M] [--turn1-variant V] [--yes]   # turn 1 only, 38 compounds, seed 0
    python -m sor.run dryrun  [--model M] [--turn1-variant V] [--yes]   # full pipeline, 3 compounds, seed 0
    python -m sor.run full    [--model M] [--turn1-variant V] [--yes]   # full pipeline, 38 compounds x seeds

M = primary | secondary (config.yaml), V = with_nsc | no_nsc | both (default both).
Every command first prints calls needed, calls already cached, estimated cost and the ledger total, and only
calls the API with --yes (a plan with zero uncached calls runs without it, at $0).
Output: runs/<run_id>/raw.jsonl (one line per call or skipped cell) + meta.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from sor.budget import Budget, BudgetExceeded, price_usd
from sor.client import CallResult, ModelClient, ParamUnsupported, count_tokens
from sor.config import ROOT, VARIANTS, load_config, model_entry, path
from sor.load import evidence_text, load_compounds
from sor.parse import parse_answer
from sor.prompts import (AUTHORITY, CONDITIONS, EVIDENCE_LEVELS, parse_condition, reviewer_message, turn1_messages,
                         turn2_messages)
from sor.targets import atlas_support, compute_targets, evidence_snippets

N_DRYRUN = 3


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_client(cfg: dict, transport=None) -> ModelClient:
    budget = Budget(path(cfg, "ledger"), cfg["budget_cap_usd"], cfg["hard_limit_usd"])
    return ModelClient(cfg, budget, path(cfg, "cache"), transport=transport)


# --- planning ---------------------------------------------------------------------------------------

def turn1_jobs(compounds: list[dict], variants: list[str], seeds: list[int]) -> list[dict]:
    jobs = []
    for c in compounds:
        for v in variants:
            msgs = turn1_messages(evidence_text(c, v))
            for s in seeds:
                jobs.append({"compound": c, "variant": v, "seed": s, "messages": msgs})
    return jobs


def turn2_cells(job: dict, t1: CallResult, parsed: dict, cfg: dict) -> tuple[dict, list[dict], list[dict]]:
    """Turn-1 outcome -> (targets, runnable cells, skipped cells)."""
    c = job["compound"]
    if t1.status != "ok":
        targets = {"turn1_moa": None, "true_moa": c["true_moa"], "correct_target": None, "misleading_target": None,
                   "skip_reason": "N/A: turn-1 error"}
    else:
        targets = compute_targets(c, parsed["moa"])
    if targets["turn1_moa"] is None:
        return targets, [], [{"condition": k, "reason": targets["skip_reason"]} for k in CONDITIONS]
    run, skip = [], []
    k, min_abs = cfg["targets"]["k_features"], cfg["targets"]["min_centroid_abs_z"]
    answer = targets["turn1_moa"]
    for cond in CONDITIONS:
        p = parse_condition(cond)
        target, snippets, atlas = None, None, None
        if cond != "control":
            target = targets["correct_target"] if p["direction"] == "correct" else targets["misleading_target"]
            if target is None:
                skip.append({"condition": cond, "reason": targets["skip_reason"]})
                continue
            if p["evidence"] == "evidence":
                snippets = evidence_snippets(c, target, k, min_abs)
            elif p["evidence"] == "atlas":
                atlas = atlas_support(c, target, answer)
        msgs = turn2_messages(job["messages"], t1.text, reviewer_message(cond, target, snippets, atlas, answer))
        run.append({"condition": cond, "target": target, "snippets": snippets, "atlas": atlas, "messages": msgs})
    return targets, run, skip


def estimate(cfg: dict, client: ModelClient, model_id: str, compounds: list[dict], variants: list[str],
             seeds: list[int], with_turn2: bool) -> dict:
    """Calls needed / cached and expected + worst-case cost. Turn-2 counts are exact where turn 1 is cached;
    otherwise expected uses the source run's first call as a prior (right -> control + misleading cells, wrong ->
    every condition) and the worst case assumes every turn 1 wrong."""
    entry = model_entry(cfg, model_id)
    est = cfg["estimate"]
    margin, exp_out, t1_ans = est["input_token_margin"], est["expected_output_tokens"], est["turn1_answer_tokens"]
    temp = cfg["temperature"]
    out = {"turn1_calls": 0, "turn1_cached": 0, "turn2_calls_known": 0, "turn2_cached": 0,
           "turn2_calls_expected": 0, "turn2_calls_max": 0, "cost_expected": 0.0, "cost_max": 0.0,
           "input_tokens_turn1_mean": 0.0}
    tok_sum = 0
    sample_review = count_tokens([{"role": "user", "content": reviewer_message(
        "auth-high_ev-evidence_dir-misleading", "Microtubule destabilizers",
        [{"feature": "tub_glcm_contrast", "value": 10.0}] * 3)}])
    for job in turn1_jobs(compounds, variants, seeds):
        n_in = count_tokens(job["messages"])
        tok_sum += n_in
        out["turn1_calls"] += 1
        hit = client.peek(model_id, job["messages"], temp, job["seed"])
        if hit:
            out["turn1_cached"] += 1
        else:
            out["cost_expected"] += price_usd(entry, int(n_in * margin), exp_out)
            out["cost_max"] += price_usd(entry, int(n_in * margin), cfg["max_tokens"])
        if not with_turn2:
            continue
        if hit:
            _, cells, _ = turn2_cells(job, hit, parse_answer(hit.text), cfg)
            out["turn2_calls_known"] += len(cells)
            out["turn2_calls_expected"] += len(cells)
            out["turn2_calls_max"] += len(cells)
            for cell in cells:
                if client.peek(model_id, cell["messages"], temp, job["seed"]):
                    out["turn2_cached"] += 1
                    continue
                n2 = count_tokens(cell["messages"])
                out["cost_expected"] += price_usd(entry, int(n2 * margin), exp_out)
                out["cost_max"] += price_usd(entry, int(n2 * margin), cfg["max_tokens"])
        else:
            n2 = n_in + t1_ans + sample_review
            n_all = len(CONDITIONS)
            n_exp = 1 + len(AUTHORITY) * len(EVIDENCE_LEVELS) if job["compound"].get("source_first_correct") else n_all
            out["turn2_calls_expected"] += n_exp
            out["turn2_calls_max"] += n_all
            out["cost_expected"] += n_exp * price_usd(entry, int(n2 * margin), exp_out)
            out["cost_max"] += n_all * price_usd(entry, int(n2 * margin), cfg["max_tokens"])
    out["input_tokens_turn1_mean"] = round(tok_sum / max(1, out["turn1_calls"]))
    out["uncached_calls_expected"] = (out["turn1_calls"] - out["turn1_cached"]
                                      + out["turn2_calls_expected"] - out["turn2_cached"])
    out["uncached_calls_max"] = out["turn1_calls"] - out["turn1_cached"] + out["turn2_calls_max"] - out["turn2_cached"]
    return out


def print_plan(name: str, model_id: str, plan: dict, client: ModelClient, cfg: dict) -> None:
    print(f"== {name} | model {model_id} | temperature {cfg['temperature']} | max_tokens {cfg['max_tokens']}")
    print(f"   turn-1 calls: {plan['turn1_calls']} (cached {plan['turn1_cached']}); mean prompt "
          f"~{plan['input_tokens_turn1_mean']} tokens (proxy tokenizer)")
    if plan["turn2_calls_max"]:
        print(f"   turn-2 calls: expected {plan['turn2_calls_expected']}, max {plan['turn2_calls_max']} "
              f"(known from cached turn 1: {plan['turn2_calls_known']}, cached {plan['turn2_cached']})")
    print(f"   uncached calls: expected {plan['uncached_calls_expected']}, max {plan['uncached_calls_max']}")
    print(f"   estimated cost: expected ${plan['cost_expected']:.3f} "
          f"(output {cfg['estimate']['expected_output_tokens']} tok/call), worst case ${plan['cost_max']:.3f} "
          f"(every call uses max_tokens)")
    print(f"   ledger total so far: ${client.budget.total():.4f}; kill switch at ${cfg['budget_cap_usd']:.2f}")


# --- execution --------------------------------------------------------------------------------------

class Run:
    def __init__(self, cfg: dict, client: ModelClient, command: str, model_id: str, variants: list[str],
                 seeds: list[int], compounds: list[dict], with_turn2: bool, args: dict):
        self.cfg, self.client, self.command, self.model = cfg, client, command, model_id
        self.variants, self.seeds, self.compounds, self.with_turn2 = variants, seeds, compounds, with_turn2
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
        vtag = variants[0] if len(variants) == 1 else "both"
        self.run_id = f"{command}_{model_id}_{vtag}_{stamp}"
        self.dir = path(cfg, "runs") / self.run_id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.raw = self.dir / "raw.jsonl"
        self.lock = threading.Lock()
        self.stop_reason: str | None = None
        self.counts = {"calls": 0, "cached": 0, "errors": 0, "skipped": 0, "unparsed": 0}
        self.cost = 0.0
        self.meta = {"run_id": self.run_id, "command": command, "model": model_id, "variants": variants,
                     "seeds": seeds, "compounds": [c["compound_id"] for c in compounds], "args": args,
                     "temperature": cfg["temperature"], "max_tokens": cfg["max_tokens"],
                     "send_seed": cfg.get("send_seed"), "send_temperature": cfg.get("send_temperature"),
                     "reasoning_effort": cfg.get("reasoning_effort"), "base_url": cfg["base_url"],
                     "git_commit": _git_commit(), "started": now(), "status": "running"}
        self._write_meta()

    def _write_meta(self) -> None:
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=1), encoding="utf-8")

    def _emit(self, rec: dict) -> None:
        with self.lock:
            with self.raw.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _base(self, job: dict) -> dict:
        c = job["compound"]
        return {"run_id": self.run_id, "timestamp": now(), "model": self.model, "turn1_variant": job["variant"],
                "seed": job["seed"], "temperature": self.cfg["temperature"], "compound_id": c["compound_id"],
                "true_moa": c["true_moa"]}

    def _call(self, job: dict, messages: list[dict], tag: str) -> CallResult:
        res = self.client.call_model(messages, job["seed"], self.cfg["temperature"], self.model, tag)
        with self.lock:
            self.counts["calls"] += 1
            self.counts["cached"] += res.cached
            self.counts["errors"] += res.status != "ok"
            self.cost += res.cost_usd
        return res

    @staticmethod
    def _result_fields(res: CallResult, parsed: dict) -> dict:
        return {"raw_text": res.text, "reasoning_text": res.reasoning_text, "moa": parsed["moa"],
                "confidence": parsed["confidence"], "rationale": parsed["rationale"],
                "parse_status": parsed["parse_status"] if res.status == "ok" else "error",
                "tokens": {"input": res.input_tokens, "output": res.output_tokens,
                           "reasoning": res.reasoning_tokens},
                "cost_usd": res.cost_usd, "original_cost_usd": res.original_cost_usd, "cached": res.cached,
                "latency_s": res.latency_s, "finish_reason": res.finish_reason, "status": res.status,
                "error": res.error, "cache_key": res.cache_key}

    def do_turn1(self, job: dict) -> tuple[dict, CallResult, dict]:
        c = job["compound"]
        tag = f"{self.command}:{c['compound_id']}:{job['variant']}:s{job['seed']}:turn1"
        res = self._call(job, job["messages"], tag)
        parsed = parse_answer(res.text) if res.status == "ok" else parse_answer(None)
        targets, cells, skipped = turn2_cells(job, res, parsed, self.cfg) if self.with_turn2 else (
            compute_targets(c, parsed["moa"]) if res.status == "ok" else None, [], [])
        rec = {**self._base(job), "turn": 1, "condition": "turn1", "target_moa": None, "evidence_snippets": None,
               "messages": job["messages"], **self._result_fields(res, parsed), "flipped": None,
               "correct": (parsed["moa"] == c["true_moa"]) if parsed["moa"] else None, "followed_target": None,
               "turn1_moa": parsed["moa"], "targets": targets,
               "planned_conditions": [x["condition"] for x in cells]}
        self._emit(rec)
        with self.lock:
            self.counts["unparsed"] += res.status == "ok" and parsed["parse_status"] == "unparsed"
        for s in skipped:
            self._emit({**self._base(job), "turn": 2, "condition": s["condition"], "target_moa": None,
                        "status": "skipped", "skip_reason": s["reason"], "turn1_moa": parsed["moa"], "cached": False,
                        "cost_usd": 0.0})
            with self.lock:
                self.counts["skipped"] += 1
        return job, res, {"parsed": parsed, "cells": cells}

    def do_turn2(self, job: dict, turn1_moa: str, cell: dict) -> None:
        c = job["compound"]
        tag = f"{self.command}:{c['compound_id']}:{job['variant']}:s{job['seed']}:{cell['condition']}"
        res = self._call(job, cell["messages"], tag)
        parsed = parse_answer(res.text) if res.status == "ok" else parse_answer(None)
        moa = parsed["moa"]
        self._emit({**self._base(job), "turn": 2, "condition": cell["condition"], "target_moa": cell["target"],
                    "evidence_snippets": cell["snippets"], "atlas_evidence": cell.get("atlas"),
                    "messages": cell["messages"],
                    **self._result_fields(res, parsed),
                    "flipped": (moa != turn1_moa) if moa else None,
                    "correct": (moa == c["true_moa"]) if moa else None,
                    "followed_target": (moa == cell["target"]) if (moa and cell["target"]) else None,
                    "turn1_moa": turn1_moa})
        with self.lock:
            self.counts["unparsed"] += res.status == "ok" and parsed["parse_status"] == "unparsed"

    def _pool(self, fn, items) -> list:
        results = []
        with ThreadPoolExecutor(max_workers=self.cfg["concurrency"]) as ex:
            futures = [ex.submit(fn, *it) for it in items]
            done, pending = wait(futures, return_when=FIRST_EXCEPTION)
            for f in futures:
                if f.done() and f.exception() is not None and self.stop_reason is None:
                    self.stop_reason = f"{type(f.exception()).__name__}: {f.exception()}"
            if self.stop_reason:
                for f in pending:
                    f.cancel()
                ex.shutdown(wait=True, cancel_futures=True)
            for f in futures:
                if f.done() and not f.cancelled() and f.exception() is None:
                    results.append(f.result())
        return results

    def execute(self) -> int:
        jobs = turn1_jobs(self.compounds, self.variants, self.seeds)
        t1 = self._pool(self.do_turn1, [(j,) for j in jobs])
        if self.with_turn2 and not self.stop_reason:
            items = [(job, info["parsed"]["moa"], cell) for job, _, info in t1 for cell in info["cells"]]
            self._pool(self.do_turn2, items)
        self.meta.update({"finished": now(), "counts": self.counts, "cost_usd_this_run": round(self.cost, 6),
                          "ledger_total_usd": round(self.client.budget.total(), 6),
                          "status": "stopped: " + self.stop_reason if self.stop_reason else "done"})
        self._write_meta()
        print(f"run {self.run_id}: {self.meta['status']}; {self.counts}; cost this run ${self.cost:.4f}; "
              f"ledger ${self.meta['ledger_total_usd']:.4f}")
        print(f"   -> {self.raw.relative_to(ROOT) if self.raw.is_relative_to(ROOT) else self.raw}")
        return 0 if not self.stop_reason else 2


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


# --- commands ---------------------------------------------------------------------------------------

def choose_dryrun(compounds: list[dict], client: ModelClient, model_id: str, variants: list[str],
                  temperature: float) -> tuple[list[dict], str]:
    """Up to 2 compounds wrong at turn 1 + 1 right, by sorted compound_id. 'Wrong' comes from cached pilot turn-1
    answers (seed 0) when present, else from the source run's first call."""
    def pilot_wrong(c):
        verdicts = []
        for v in variants:
            hit = client.peek(model_id, turn1_messages(evidence_text(c, v)), temperature, 0)
            if hit:
                moa = parse_answer(hit.text)["moa"]
                verdicts.append(moa is not None and moa != c["true_moa"])
        return any(verdicts) if verdicts else None

    info = {c["compound_id"]: pilot_wrong(c) for c in compounds}
    if all(v is not None for v in info.values()):
        wrong = [c for c in compounds if info[c["compound_id"]]]
        rule = "cached pilot turn-1 answers"
    else:
        wrong = [c for c in compounds if not c.get("source_first_correct")]
        rule = "source run first call (no complete pilot cache)"
    wrong = sorted(wrong, key=lambda c: c["compound_id"])[:2]
    right = sorted((c for c in compounds if c not in wrong), key=lambda c: c["compound_id"])
    return wrong + right[:N_DRYRUN - len(wrong)], rule


def cmd_estimate(cfg: dict, client: ModelClient, compounds: list[dict]) -> int:
    for which in ("primary", "secondary"):
        mid = model_entry(cfg, which)["id"]
        dry, _ = choose_dryrun(compounds, client, mid, list(VARIANTS), cfg["temperature"])
        specs = [("pilot (turn 1, 38 x seed 0, both variants)", compounds, list(VARIANTS), [0], False),
                 ("dryrun (3 compounds, seed 0, both variants)", dry, list(VARIANTS), [0], True),
                 ("full (38 x 3 seeds, both variants)", compounds, list(VARIANTS), cfg["seeds"], True)]
        specs += [(f"full (38 x 3 seeds, {v} only)", compounds, [v], cfg["seeds"], True) for v in VARIANTS]
        for name, cs, vs, seeds, t2 in specs:
            print_plan(name, mid, estimate(cfg, client, mid, cs, vs, seeds, t2), client, cfg)
        print()
    return 0


def cmd_probe(cfg: dict, client: ModelClient, model_id: str, yes: bool) -> int:
    msgs = [{"role": "user", "content": "Reply with the single word OK."}]
    cached = client.peek(model_id, msgs, cfg["temperature"], 0)
    print(f"== probe | model {model_id} | sends temperature={cfg['temperature'] if cfg.get('send_temperature') else '-'}"
          f" seed={'0' if cfg.get('send_seed') else '-'} | cached: {bool(cached)} | max cost "
          f"${client.max_cost(model_id, msgs):.4f} | ledger ${client.budget.total():.4f}")
    if not cached and not yes:
        print("   not sent: add --yes to make this call")
        return 0
    if not cached and not os.environ.get(cfg["api_key_env"]):
        print(f"   {cfg['api_key_env']} is not set")
        return 1
    try:
        res = client.call_model(msgs, 0, cfg["temperature"], model_id, "probe")
    except ParamUnsupported as exc:
        print(f"   REJECTED: {exc}")
        return 2
    print(f"   status={res.status} finish={res.finish_reason} text={res.text[:60]!r} tokens in/out/reasoning="
          f"{res.input_tokens}/{res.output_tokens}/{res.reasoning_tokens} cost=${res.original_cost_usd:.5f}"
          + (f" error={res.error}" if res.error else ""))
    return 0 if res.status == "ok" else 1


def main(argv: list[str] | None = None, transport=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sor.run")
    ap.add_argument("command", choices=["estimate", "probe", "pilot", "dryrun", "full"])
    ap.add_argument("--model", default="primary", help="primary | secondary (config.yaml)")
    ap.add_argument("--turn1-variant", default="both", choices=[*VARIANTS, "both"])
    ap.add_argument("--seeds", default=None, help="comma-separated seeds for full (default: config.yaml)")
    ap.add_argument("--max-spend", type=float, default=None,
                    help="stop this run once it has spent this many USD (kill switch = ledger + this, never above cap)")
    ap.add_argument("--yes", action="store_true", help="allow real (paid) API calls")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    client = make_client(cfg, transport)
    if a.max_spend is not None:
        client.budget.cap_usd = min(client.budget.cap_usd, client.budget.total() + a.max_spend)
        print(f"   run spend limit ${a.max_spend:.2f}: kill switch lowered to ${client.budget.cap_usd:.4f}")
    compounds = load_compounds()
    model_id = model_entry(cfg, a.model)["id"]
    variants = list(VARIANTS) if a.turn1_variant == "both" else [a.turn1_variant]

    if a.command == "estimate":
        return cmd_estimate(cfg, client, compounds)
    if a.command == "probe":
        return cmd_probe(cfg, client, model_id, a.yes)

    if a.command == "pilot":
        cs, seeds, t2 = compounds, [0], False
    elif a.command == "dryrun":
        cs, rule = choose_dryrun(compounds, client, model_id, variants, cfg["temperature"])
        print(f"dryrun compounds ({rule}): {[c['compound_id'] for c in cs]}")
        seeds, t2 = [0], True
    else:
        seeds = [int(s) for s in a.seeds.split(",")] if a.seeds else list(cfg["seeds"])
        cs, t2 = compounds, True

    plan = estimate(cfg, client, model_id, cs, variants, seeds, t2)
    print_plan(a.command, model_id, plan, client, cfg)
    if plan["uncached_calls_max"] > 0:
        if not a.yes:
            print("   nothing sent: re-run with --yes to make the real calls")
            return 0
        if not os.environ.get(cfg["api_key_env"]) and transport is None:
            print(f"   {cfg['api_key_env']} is not set; nothing sent")
            return 1
    run = Run(cfg, client, a.command, model_id, variants, seeds, cs, t2,
              {"turn1_variant": a.turn1_variant, "seeds": a.seeds, "max_spend": a.max_spend, "yes": a.yes})
    try:
        return run.execute()
    except (BudgetExceeded, ParamUnsupported) as exc:
        run.stop_reason = str(exc)
        run.meta.update({"status": f"stopped: {exc}", "finished": now(), "counts": run.counts})
        run._write_meta()
        print(f"STOPPED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
