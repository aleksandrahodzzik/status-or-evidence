"""Spend ledger + kill switch.

budget/ledger.jsonl gets one line per real API call (cache hits never touch it), so totals survive restarts.
Before every real call the caller reserves the call's worst-case cost (estimated input tokens + max_tokens as
output). If ledger total + in-flight reservations + this estimate exceeds budget_cap_usd, BudgetExceeded is raised
and the call is never sent.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


def price_usd(entry: dict, input_tokens: int, output_tokens: int) -> float:
    return input_tokens * entry["price_in_per_m"] / 1e6 + output_tokens * entry["price_out_per_m"] / 1e6


class Budget:
    def __init__(self, ledger_path: Path, cap_usd: float, hard_limit_usd: float):
        if cap_usd > hard_limit_usd:
            raise ValueError("budget cap may not exceed the hard limit")
        self.ledger_path = Path(ledger_path)
        self.cap_usd = cap_usd
        self.hard_limit_usd = hard_limit_usd
        self.reserved = 0.0
        self._lock = threading.Lock()

    def total(self) -> float:
        if not self.ledger_path.exists():
            return 0.0
        total = 0.0
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                total += float(json.loads(line).get("cost_usd") or 0.0)
            except (ValueError, TypeError):
                continue
        return total

    def reserve(self, estimate_usd: float) -> float:
        with self._lock:
            spent = self.total()
            if spent + self.reserved + estimate_usd > min(self.cap_usd, self.hard_limit_usd):
                raise BudgetExceeded(
                    f"kill switch: ledger ${spent:.4f} + in flight ${self.reserved:.4f} + this call's max "
                    f"${estimate_usd:.4f} > cap ${self.cap_usd:.2f}. Nothing sent; everything so far is saved.")
            self.reserved += estimate_usd
            return estimate_usd

    def release(self, reservation: float) -> None:
        with self._lock:
            self.reserved = max(0.0, self.reserved - reservation)

    def record(self, reservation: float, line: dict) -> None:
        """Append one real call to the ledger and drop its reservation."""
        with self._lock:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **line}
            with self.ledger_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            self.reserved = max(0.0, self.reserved - reservation)
