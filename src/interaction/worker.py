"""Bounded daemon worker: slow inference cannot block ticks or process shutdown."""
from concurrent.futures import Future
from queue import Queue, Full
from threading import Thread


class Worker:
    def __init__(self, name):
        self.queue = Queue(maxsize=1)
        self.closed = False
        self.thread = Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def submit(self, function, *args):
        future = Future()
        if self.closed:
            raise RuntimeError("voice worker closed")
        try:
            self.queue.put_nowait((future, function, args))
        except Full:
            raise RuntimeError("voice worker busy") from None
        return future

    def _run(self):
        while True:
            job = self.queue.get()
            if job is None:
                return
            future, function, args = job
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args))
                except Exception as exc:
                    future.set_exception(exc)
            if self.closed:
                return

    def close(self):
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except Full:
            pass
