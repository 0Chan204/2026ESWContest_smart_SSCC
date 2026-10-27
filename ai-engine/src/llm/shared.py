"""One lazy client, bounded failure recovery, and per-voice deadline overrides."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from math import isfinite
from threading import Lock
import time

from .adapters.base import (
    BaseLLMAdapter, LLMNotConfiguredError, LLMRequestTimeoutError, LLMServiceError,
    LLMAuthenticationError, LLMResponseError,
)
from .factory import create_llm, resolve_llm_provider


class SharedLLM(BaseLLMAdapter):
    def __init__(self, factory=None, *, clock=time.time, provider=None, failure_retry_seconds=30.0):
        if (type(failure_retry_seconds) not in (int, float)
                or not isfinite(failure_retry_seconds) or failure_retry_seconds <= 0):
            raise ValueError("failure_retry_seconds must be finite and positive")
        self.factory = factory or create_llm
        self.provider = provider
        self.clock = clock
        self.failure_retry_seconds = failure_retry_seconds
        self._adapter = None
        self._loaded = False
        self._lock = Lock()
        # Status must remain readable while inference holds the model lock.
        self._status_lock = Lock()
        self._status = {"provider": resolve_llm_provider(provider), "state": "uninitialized",
                        "fallback_active": False, "failures": 0, "last_error": None, "retry_at": None}
        self._deadline = ContextVar("homevis_llm_deadline", default=None)
        self._prepared = ContextVar("homevis_llm_prepared", default=None)

    @property
    def name(self):
        return self._adapter.name if self._adapter is not None else resolve_llm_provider(self.provider)

    def health(self):
        with self._status_lock:
            return dict(self._status)

    def _update_status(self, **values):
        with self._status_lock:
            self._status.update(values)

    @contextmanager
    def deadline(self, deadline):
        token = self._deadline.set(deadline)
        try:
            yield
        finally:
            self._deadline.reset(token)

    @contextmanager
    def prepared(self, result):
        """Replay exactly one validated inference to the existing feedback service.

        A cache miss fails closed; never start inference on the controller thread.
        """
        token = self._prepared.set(result)
        try:
            yield
        finally:
            self._prepared.reset(token)

    def generate(self, system_prompt, user_prompt):
        prepared = self._prepared.get()
        if prepared is not None:
            if prepared[:2] != [system_prompt, user_prompt]:
                raise LLMNotConfiguredError("prepared feedback context mismatch")
            return prepared[2]
        deadline = self._deadline.get()
        remaining = None if deadline is None else deadline - self.clock()
        acquired = self._lock.acquire() if remaining is None else (
            remaining > 0 and self._lock.acquire(timeout=remaining))
        if not acquired:
            raise LLMRequestTimeoutError("LLM deadline while waiting for shared model")
        try:
            retry_at = self.health()["retry_at"]
            if retry_at is not None and self.clock() < retry_at:
                raise LLMServiceError("Selected LLM is temporarily unavailable; use fallback")
            return self._generate(system_prompt, user_prompt, deadline)
        finally:
            self._lock.release()

    def _generate(self, system_prompt, user_prompt, deadline):
        try:
            if not self._loaded:
                self._adapter = self.factory()
                self._loaded = True
            if self._adapter is None:
                self._update_status(state="disabled", fallback_active=True, retry_at=None)
                raise LLMNotConfiguredError("LLM is disabled")
            adapter = self._adapter
            if deadline is not None:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise LLMRequestTimeoutError("LLM deadline exceeded")
                if adapter.name in {"gpt", "exaone"}:
                    adapter = copy(adapter)
                    adapter.client = adapter.client.with_options(
                        timeout=min(remaining, getattr(adapter, "timeout", remaining)), max_retries=0)
                elif hasattr(adapter, "with_timeout"):
                    adapter = adapter.with_timeout(remaining)
            result = adapter.generate(system_prompt, user_prompt)
            if deadline is not None and self.clock() >= deadline:
                raise LLMRequestTimeoutError("LLM result arrived after deadline")
            self._update_status(state="ready", fallback_active=False, failures=0, last_error=None, retry_at=None)
            return result
        except Exception as exc:
            if not (self._loaded and self._adapter is None):
                self._update_status(state="degraded", fallback_active=True,
                                    failures=self.health()["failures"] + 1,
                                    last_error=type(exc).__name__,
                                    retry_at=self.clock() + self.failure_retry_seconds)
            # Do not expose SDK exception bodies or chained tracebacks. Keep the
            # existing client and provider for recovery on the next eligible call.
            safe_type = type(exc) if isinstance(exc, (LLMNotConfiguredError, LLMRequestTimeoutError,
                LLMServiceError, LLMAuthenticationError, LLMResponseError)) else LLMServiceError
            raise safe_type("Selected LLM unavailable; use fallback") from None
