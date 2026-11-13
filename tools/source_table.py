"""Markdown table of the chosen source transcript per compound (from data/compounds.jsonl)."""

from collections import Counter

from sor.load import load_compounds


def main() -> None:
    cs = load_compounds()
    print("| compound_id | true MoA | source run | source Scientist first call | wells/phenotype/dose/atlas blocks |")
    print("|---|---|---|---|---|")
    for c in sorted(cs, key=lambda c: (c["true_moa"], c["compound_id"])):
        k = Counter(b["kind"] for b in c["evidence_blocks"])
        verdict = "right" if c["source_first_correct"] else "wrong"
        print(f"| {c['compound_id']} | {c['true_moa']} | {c['source_run_id']} | {c['source_first_moa']} ({verdict}) "
              f"| {k['well']}/{k['phenotype']}/{k['dose_response']}/{k['atlas']} |")
    print(f"\nSource rule used: {dict(Counter(c['source_rule'] for c in cs))}")
    print(f"Source Scientist first call right: {sum(bool(c['source_first_correct']) for c in cs)}/38")
    print(f"Compounds per MoA: {dict(sorted(Counter(c['true_moa'] for c in cs).items()))}")


if __name__ == "__main__":
    main()
