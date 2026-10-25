"""One lazy model/client, serialized inference, and per-voice deadline overrides."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from threading import Lock
import time

from .adapters.base import BaseLLMAdapter, LLMNotConfiguredError, LLMRequestTimeoutError
from .factory import create_llm, resolve_llm_provider


class SharedLLM(BaseLLMAdapter):
    def __init__(self, factory=None, *, clock=time.time):
        self.factory = factory or create_llm
        self.clock = clock
        self._adapter = None
        self._loaded = False
        self._lock = Lock()
        self._deadline = ContextVar("homevis_llm_deadline", default=None)
        self._prepared = ContextVar("homevis_llm_prepared", default=None)

    @property
    def name(self):
        return self._adapter.name if self._adapter is not None else resolve_llm_provider()

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
            if not self._loaded:
                self._adapter = self.factory()
                self._loaded = True
            if self._adapter is None:
                raise LLMNotConfiguredError("LLM is disabled")
            adapter = self._adapter
            if deadline is not None:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise LLMRequestTimeoutError("LLM deadline exceeded")
                if adapter.name in {"gpt", "exaone"}:
                    adapter = copy(adapter)
                    adapter.client = adapter.client.with_options(timeout=remaining, max_retries=0)
            result = adapter.generate(system_prompt, user_prompt)
            if deadline is not None and self.clock() >= deadline:
                raise LLMRequestTimeoutError("LLM result arrived after deadline")
            return result
        finally:
            self._lock.release()
