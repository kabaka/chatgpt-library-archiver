"""Utilities for consistent status logging and progress bars."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from tqdm import tqdm


def format_status(action: str, detail: str) -> str:
    """Return a standardized status message."""

    action = action.strip()
    detail = detail.strip()
    if not action:
        return detail
    if not detail:
        return action
    return f"{action} {detail}"


@dataclass(slots=True)
class StatusError:
    """Structured error information captured during a run."""

    action: str
    detail: str
    reason: str
    context: dict[str, object] = field(default_factory=dict)
    exception: Exception | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action": self.action,
            "detail": self.detail,
            "reason": self.reason,
        }
        if self.context:
            payload["context"] = dict(self.context)
        if self.exception is not None:
            payload["exception"] = repr(self.exception)
        return payload


@dataclass
class StatusReporter(AbstractContextManager["StatusReporter"]):
    """Helper for logging messages while keeping a progress bar at the bottom."""

    total: int | None = None
    description: str = ""
    unit: str = "item"
    position: int = 0
    disable: bool | None = None
    errors: list[StatusError] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._bar = None
        self._bar_kwargs = {
            "desc": self.description,
            "unit": self.unit,
            "dynamic_ncols": True,
            "position": self.position,
            "leave": False,
            "file": sys.stdout,
        }
        if self.disable is None:
            self.disable = not sys.stdout.isatty()
        self._bar_kwargs["disable"] = self.disable
        if self.total is not None:
            self._create_bar(self.total)

    def _create_bar(self, total: int) -> None:
        if self._bar is None:
            self._bar = tqdm(total=total, **self._bar_kwargs)
        else:
            self._bar.total = total
            self._bar.refresh()

    def log(self, message: str) -> None:
        """Log ``message`` above the progress bar."""

        if self._bar is not None:
            tqdm.write(message, file=sys.stdout)
        else:
            print(message, file=sys.stdout, flush=True)

    def log_status(self, action: str, detail: str) -> None:
        self.log(format_status(action, detail))

    def report_error(
        self,
        action: str,
        detail: str,
        *,
        reason: str,
        context: Mapping[str, object] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Record and display a structured error message."""

        error = StatusError(
            action=action,
            detail=detail,
            reason=reason,
            context=dict(context or {}),
            exception=exception,
        )
        self.errors.append(error)
        message = format_status(action, detail)
        message = f"ERROR {message}: {reason}" if reason else f"ERROR {message}"
        self.log(message)

    def advance(self, amount: int = 1) -> None:
        if self._bar is None:
            return
        self._bar.update(amount)

    def set_total(self, total: int) -> None:
        if self._bar is None:
            self._create_bar(total)
        else:
            self._bar.total = total
            self._bar.refresh()

    def add_total(self, amount: int) -> None:
        if amount <= 0:
            return
        if self._bar is None:
            self._create_bar(amount)
        else:
            self._bar.total += amount
            self._bar.refresh()

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None

    def __exit__(self, exc_type, exc, exc_tb):
        self.close()
        return False
