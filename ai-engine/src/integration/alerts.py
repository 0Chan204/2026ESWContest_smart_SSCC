"""Keep LLM/TTS latency off the sensing/controller thread."""
from queue import Empty, Full, Queue
from threading import Thread


class AlertWorker:
    def __init__(self, service_factory):
        self.factory = service_factory
        self.requests = Queue(maxsize=8)
        self.results = Queue(maxsize=8)
        self.thread = Thread(target=self._run, name="homevis-alerts", daemon=True)
        self.thread.start()

    def submit(self, decision, incident_id):
        try:
            self.requests.put_nowait((decision, incident_id))
            return True
        except Full:
            return False

    def _run(self):
        service = None
        while True:
            job = self.requests.get()
            if job is None:
                return
            decision, incident_id = job
            try:
                if service is None:
                    service = self.factory()
                detail = {"incident_id": incident_id, "result": service.handle(decision).to_dict()}
            except Exception as exc:
                # Third-party exceptions can contain credentials or URLs.
                detail = {"incident_id": incident_id, "error": type(exc).__name__}
            try:
                self.results.put_nowait(detail)
            except Full:
                pass

    def drain(self):
        while True:
            try:
                yield self.results.get_nowait()
            except Empty:
                return

    def close(self):
        while True:
            try:
                self.requests.get_nowait()
            except Empty:
                break
        self.requests.put_nowait(None)
