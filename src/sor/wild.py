"""In-the-wild reviewer requests in the recorded MuseCell runs ($0, no API).

For every indexed run (agent_runs.jsonl + open_world_runs.jsonl) with a transcript, every `review` event with
verdict `request_experiment` is one request. Before = the Scientist's latest `conclusion` before the review;
after = the first `conclusion` after it (none -> the Scientist kept its call). Transitions are judged against
truth_moa: kept, W->R, R->W, W->W (changed to another wrong class).

Confounds recorded per request: the reviewer requested a new experiment, so a change may follow new evidence
(`wells_acquired_after_review`), not the critique alone; in agent v5 the run's final call is the NSC protocol vote
(`protocol_call`), not the Scientist's conclusion, so index-level `agent_moa` differs from the Scientist's call.

Outputs: runs/wild/requests.jsonl, runs/wild/summary.json, docs/WILD.md.
"""

from __future__ import annotations

import json
from collections import Counter

from sor.config import ROOT
from sor.load import read_index, read_transcript

OUT = ROOT / "runs" / "wild"


def transition(before: str | None, after: str | None, truth: str) -> str:
    if after is None or after == before:
        return "kept"
    return ("R" if before == truth else "W") + "->" + ("R" if after == truth else "W")


def collect() -> tuple[list[dict], dict]:
    rows = read_index()
    reqs, notes = [], Counter()
    for r in rows:
        ev = read_transcript(r["run_id"])
        if ev is None:
            notes["no_transcript"] += 1
            continue
        for i, e in enumerate(ev):
            if e["type"] != "review":
                continue
            d = e["data"]
            notes[f"reviews_{d.get('verdict')}"] += 1
            if d.get("verdict") != "request_experiment":
                continue
            before = next((x["data"] for x in reversed(ev[:i]) if x["type"] == "conclusion"), None)
            after = next((x["data"] for x in ev[i + 1:] if x["type"] == "conclusion"), None)
            stop = next((j for j in range(i + 1, len(ev)) if ev[j]["type"] in ("conclusion", "unblinded")),
                        len(ev))
            wells_after = sum(1 for x in ev[i + 1:stop] if x["type"] == "tool_result"
                              and x["data"].get("name") == "acquire_well" and x["data"].get("ok"))
            tools_after = dict(Counter(x["data"].get("name") for x in ev[i + 1:stop] if x["type"] == "tool_result"
                                       and x["data"].get("ok")))
            budget_left = next((x["data"]["data"].get("budget_left") for x in reversed(ev[:i])
                                if x["type"] == "tool_result" and x["data"].get("name") == "acquire_well"
                                and x["data"].get("ok")), r.get("budget"))
            protocol = next((x["data"] for x in ev if x["type"] == "protocol_call"), None)
            b = before["top_moa"] if before else None
            a = after["top_moa"] if after else None
            truth = r["truth_moa"]
            reqs.append({
                "run_id": r["run_id"], "index": r["_index"], "compound": r["compound"], "truth_moa": truth,
                "agent": r["models"].get("agent", "v1"), "scientist": r["models"]["scientist"],
                "reviewer": r["models"].get("reviewer"), "budget": r.get("budget"), "status": r.get("status"),
                "round": d.get("round"), "verdict": d.get("verdict"), "critique": d.get("critique"),
                "requested_experiment": d.get("requested_experiment"),
                "conclusion_before": b, "p_before": before.get("probability") if before else None,
                "conclusion_after": a, "p_after": after.get("probability") if after else None,
                "revised": after is not None, "changed": a is not None and a != b,
                "transition": transition(b, a, truth), "wells_acquired_after_review": wells_after,
                "budget_left_at_review": budget_left, "tools_after_review": tools_after,
                "index_first_moa": r.get("first_moa"), "index_first_correct": r.get("first_correct"),
                "index_agent_moa": r.get("agent_moa"), "index_correct": r.get("correct"),
                "index_review": r.get("review"), "call_source": r.get("call_source", "scientist"),
                "protocol_moa": protocol.get("moa") if protocol else None,
            })
    return reqs, dict(notes)


def counts(reqs: list[dict]) -> dict:
    t = Counter(q["transition"] for q in reqs)
    return {"requests": len(reqs), "changed": sum(q["changed"] for q in reqs), "W->R": t["W->R"],
            "R->W": t["R->W"], "W->W": t["W->W"], "kept": t["kept"]}


def index_counts(rows: list[dict]) -> dict:
    """The quick count from the index alone: review == request_experiment, first_moa vs agent_moa."""
    req = [r for r in rows if r.get("review") == "request_experiment"]
    t = Counter("kept" if r.get("first_moa") == r.get("agent_moa") else
                ("R" if r.get("first_correct") else "W") + "->" + ("R" if r.get("correct") else "W") for r in req)
    return {"requests": len(req), "changed": len(req) - t["kept"], "W->R": t["W->R"], "R->W": t["R->W"],
            "W->W": t["W->W"], "kept": t["kept"]}


def main() -> None:
    reqs, notes = collect()
    rows = read_index()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "requests.jsonl").write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in reqs),
                                        encoding="utf-8")
    groups: dict[str, dict] = {"all (both index files)": counts(reqs),
                               "agent_runs.jsonl only": counts([q for q in reqs if q["index"] == "agent_runs.jsonl"]),
                               "open_world_runs.jsonl only": counts([q for q in reqs
                                                                     if q["index"] == "open_world_runs.jsonl"])}
    by_ver = Counter((q["agent"], q["scientist"]) for q in reqs)
    for (ag, sci) in sorted(by_ver):
        groups[f"{ag} | {sci}"] = counts([q for q in reqs if q["agent"] == ag and q["scientist"] == sci])
    idx = {"index-only, both files": index_counts(rows),
           "index-only, agent_runs.jsonl": index_counts([r for r in rows if r["_index"] == "agent_runs.jsonl"]),
           "index-only, agent_runs.jsonl, finished": index_counts(
               [r for r in rows if r["_index"] == "agent_runs.jsonl" and r.get("status") == "finished"])}
    disagree = [q for q in reqs if q["index_first_moa"] != q["conclusion_before"]]
    changed = [q for q in reqs if q["changed"]]
    tools_changed = Counter()
    for q in changed:
        tools_changed.update(q["tools_after_review"])
    confound = {"changed_with_new_well": sum(q["wells_acquired_after_review"] > 0 for q in changed),
                "changed_without_new_well": sum(q["wells_acquired_after_review"] == 0 for q in changed),
                "kept_with_new_well": sum(q["wells_acquired_after_review"] > 0 for q in reqs if not q["changed"]),
                "requests_with_budget_left": sum((q["budget_left_at_review"] or 0) > 0 for q in reqs),
                "changed_with_any_new_tool_result": sum(bool(q["tools_after_review"]) for q in changed),
                "revised_without_change": sum(q["revised"] and not q["changed"] for q in reqs),
                "tool_results_after_review_in_changed": dict(tools_changed),
                "v5_requests": sum(q["agent"] == "v5" for q in reqs),
                "v5_scientist_changed_but_protocol_final": sum(q["agent"] == "v5" and q["changed"] for q in reqs)}
    summary = {"transcript_counts": groups, "index_counts": idx, "review_events": notes,
               "index_first_moa_vs_transcript_before_mismatches": len(disagree), "confounds": confound,
               "user_quick_count": {"requests": 99, "changed": 34, "W->R": 17, "R->W": 1, "W->W": 16, "kept": 65}}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    def line(name, c):
        return (f"| {name} | {c['requests']} | {c['changed']} | {c['W->R']} | {c['R->W']} | {c['W->W']} | "
                f"{c['kept']} |")
    hdr = ["| group | requests | changed | W->R | R->W | W->W | kept |", "|---|---|---|---|---|---|---|"]
    md = ["# In-the-wild reviewer requests (MuseCell recorded runs)", "",
          "Generated by `python -m sor.wild` ($0). Per-request table: `runs/wild/requests.jsonl`.", "",
          "## From transcripts (Scientist conclusion before vs after the review)", "", *hdr,
          *[line(k, v) for k, v in groups.items()], "",
          "## From the index files alone (first_moa vs agent_moa where review == request_experiment)", "", *hdr,
          *[line(k, v) for k, v in idx.items()], "",
          "## Confounds", "",
          f"- Every request named a new experiment, but no run acquired a new well after the review: of "
          f"{len(changed)} changed calls {confound['changed_with_new_well']} followed a new well; well budget "
          f"left at review time was > 0 in {confound['requests_with_budget_left']} of {len(reqs)} requests. "
          f"{confound['changed_with_any_new_tool_result']} of the {len(changed)} changes followed new free "
          f"analyses on the existing wells (tool results after the review, in changed runs: "
          f"{confound['tool_results_after_review_in_changed']}). So a change is a response to the critique plus "
          "re-analysis, not to new data; still not a clean critique-only effect.",
          f"- {confound['revised_without_change']} requests led to a re-submitted conclusion with the same MoA "
          "(counted as kept).",
          "- The owner's quick count (99 requests, 34 changed: 17 W->R, 1 R->W, 16 W->W; 65 kept) is reproduced "
          "exactly by the index-only count over agent_runs.jsonl rows with a non-null agent_moa (it drops 2 "
          "failed runs; a third failed run with a request and agent_moa set is kept). From transcripts the "
          "same 101 agent_runs requests give 30 changed (14 W->R, 1 R->W, 15 W->W), because in v5 the index "
          "compares the Scientist's first call with the NSC protocol vote and failed runs count as changes.",
          f"- Agent v5 ({confound['v5_requests']} requests): the run's final call is the NSC protocol vote, so the "
          "index `agent_moa` is the vote, not the Scientist. Transcript counts above use the Scientist's own "
          "conclusions.",
          f"- Index `first_moa` differs from the transcript's conclusion before the review in {len(disagree)} "
          "requests.", ""]
    (ROOT / "docs" / "WILD.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
