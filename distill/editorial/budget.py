"""Durable weekly reservations layered over Distill's request budget admission."""

from __future__ import annotations

import math
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from distill.editorial.perspective import EditorialModel, Money
from distill.jsonl import append_jsonl_line_locked, jsonl_append_lock, read_jsonl_objects_strict
from distill.llm.cost import compute_cost
from distill.llm.usage import LLMUsageAttempt
from distill.pipeline.budget import ProjectedBudgetExceededError
from distill.pipeline.costs import CostTracker


def utc_week(now: datetime | None = None) -> str:
    day = (now or datetime.now(UTC)).astimezone(UTC).date()
    return (day - timedelta(days=day.weekday())).isoformat()


class BudgetEvent(EditorialModel):
    schema_version: Literal[1] = 1
    reservation: str = Field(pattern=r"^[a-f0-9]{32}$")
    kind: Literal["reserve", "settle"]
    week: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: Money
    run_id: str = Field(min_length=1, max_length=200)


class WeeklyLedger:
    """One shared ledger per editorial workspace, across perspectives and processes.

    Unsettled reservations count in every week. A request spanning a UTC week
    boundary is charged in both weeks conservatively. Corruption fails closed.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def _events(self) -> list[BudgetEvent]:
        rows = read_jsonl_objects_strict(
            self.path, max_file_bytes=16000000, max_row_bytes=2048, max_rows=40000
        )
        events = [BudgetEvent.model_validate(row) for row in rows]
        pending: dict[str, BudgetEvent] = {}
        seen: set[str] = set()
        for event in events:
            if event.kind == "reserve":
                if event.reservation in seen:
                    raise ValueError("Duplicate budget reservation")
                pending[event.reservation] = event
                seen.add(event.reservation)
            elif event.reservation not in pending:
                raise ValueError("Budget settlement has no pending reservation")
            else:
                original = pending.pop(event.reservation)
                if original.run_id != event.run_id:
                    raise ValueError("Budget settlement run identity mismatch")
        return events

    @staticmethod
    def _used(events: list[BudgetEvent], week: str) -> float:
        starts = {e.reservation: e for e in events if e.kind == "reserve"}
        ends = {e.reservation: e for e in events if e.kind == "settle"}
        costs = []
        for identity, start in starts.items():
            end = ends.get(identity)
            if end is None:
                costs.append(start.amount)
            elif week in {start.week, end.week}:
                costs.append(end.amount)
        return math.fsum(costs)

    def status(self, weekly_usd: float) -> dict[str, object]:
        with jsonl_append_lock(self.path):
            events = self._events()
            used = self._used(events, utc_week())
        return {
            "week_start_utc": utc_week(),
            "weekly_usd": weekly_usd,
            "spent_or_reserved_usd": used,
            "remaining_usd": max(0.0, weekly_usd - used),
            "pending_reservations": sum(e.kind == "reserve" for e in events)
            - sum(e.kind == "settle" for e in events),
        }

    def reserve(self, amount: float, weekly_usd: float, run_id: str) -> BudgetEvent:
        event = BudgetEvent(
            reservation=uuid4().hex, kind="reserve", week=utc_week(), amount=amount, run_id=run_id
        )
        with jsonl_append_lock(self.path):
            projected = self._used(self._events(), event.week) + event.amount
            if projected > weekly_usd:
                raise ProjectedBudgetExceededError(projected, weekly_usd)
            append_jsonl_line_locked(self.path, event.model_dump_json(), durable=True)
        return event

    def settle(self, reservation: BudgetEvent, amount: float) -> None:
        event = BudgetEvent(
            reservation=reservation.reservation,
            kind="settle",
            week=utc_week(),
            amount=amount,
            run_id=reservation.run_id,
        )
        with jsonl_append_lock(self.path):
            events = self._events()
            if reservation not in events or any(
                e.kind == "settle" and e.reservation == reservation.reservation for e in events
            ):
                raise ValueError("Unknown or already settled reservation")
            append_jsonl_line_locked(self.path, event.model_dump_json(), durable=True)


class EditorialTracker(CostTracker):
    def __init__(self, ledger: WeeklyLedger, *, weekly_usd: float, per_run_usd: float, run_id: str):
        super().__init__(budget=per_run_usd, run_id=run_id)
        self.ledger = ledger
        self.weekly_usd = weekly_usd

    @contextmanager
    def reserve_attempt(
        self, attempt: LLMUsageAttempt, *, call_type: str = ""
    ) -> Generator[None, None, None]:
        with super().reserve_attempt(attempt, call_type=call_type):
            amount = compute_cost(attempt.model, attempt.input_tokens, attempt.output_tokens)
            reservation = self.ledger.reserve(amount, self.weekly_usd, self.run_id)
            before = self.total_cost
            try:
                yield
            except BaseException:
                # A timeout or interrupted submission may still be billed. Keep
                # the entire admission bound unless accounting proves a cost.
                actual = self.total_cost - before
                if actual > 0:
                    self.ledger.settle(reservation, actual)
                raise
            else:
                self.ledger.settle(reservation, max(0.0, self.total_cost - before))
