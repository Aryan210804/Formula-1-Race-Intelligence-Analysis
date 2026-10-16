"""Bounded retry and request pacing helpers."""

import logging
import time
from dataclasses import dataclass
from typing import Callable, TypeVar
from urllib.error import HTTPError, URLError

from f1_intelligence.data.settings import IngestionSettings

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class IngestionError(RuntimeError):
    """Raised when a source operation fails after its configured retries."""


@dataclass
class RequestController:
    """Pace source requests and retry transient source failures."""

    settings: IngestionSettings
    _last_request_at: float | None = None

    def call(self, operation: Callable[[], T], label: str) -> T:
        """Run an operation with bounded exponential backoff and request pacing."""
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            self._wait_for_request_slot()
            LOGGER.info("%s (attempt %d/%d)", label, attempt, self.settings.max_attempts)
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if (
                    attempt == self.settings.max_attempts
                    or not _is_transient_error(exc)
                ):
                    break
                delay = min(
                    self.settings.backoff_base_seconds * (2 ** (attempt - 1)),
                    self.settings.backoff_max_seconds,
                )
                LOGGER.warning(
                    "%s failed on attempt %d/%d (%s); retrying in %.2f seconds",
                    label,
                    attempt,
                    self.settings.max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)
        if last_error is None:
            raise IngestionError(f"{label} did not execute")
        raise IngestionError(
            f"{label} failed after {self.settings.max_attempts} attempt(s): "
            f"{last_error}"
        ) from last_error

    def _wait_for_request_slot(self) -> None:
        interval = self.settings.minimum_request_interval_seconds
        now = time.monotonic()
        if self._last_request_at is not None:
            delay = interval - (now - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
        self._last_request_at = time.monotonic()


def _is_transient_error(error: Exception) -> bool:
    """Recognize common transport failures without retrying data/schema errors."""
    if isinstance(error, HTTPError):
        return _retryable_http_status(error.code)
    if isinstance(error, (TimeoutError, ConnectionError, OSError, URLError)):
        return True
    if not error.__class__.__module__.startswith("requests."):
        return False
    if error.__class__.__name__ in {"ConnectionError", "Timeout", "ChunkedEncodingError"}:
        return True
    if error.__class__.__name__ == "HTTPError":
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        return isinstance(status_code, int) and _retryable_http_status(status_code)
    return False


def _retryable_http_status(status_code: int) -> bool:
    """Retry rate limiting, temporary gateway/service errors, and request timeouts."""
    return status_code in {408, 425, 429} or 500 <= status_code <= 599
