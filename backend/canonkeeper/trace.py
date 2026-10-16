"""Run tracing. Every agent step is written to the run document so the UI can
render the live agent timeline from any instance."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from . import store


class Tracer:
    def __init__(self, run_id: str, kind: str) -> None:
        self.run_id = run_id
        self.t0 = time.time()
        store.docs().set("runs", run_id, {
            "run_id": run_id, "kind": kind, "status": "running",
            "started_at": self.t0, "finished_at": 0, "error": "", "steps": [],
        })

    def _ms(self) -> int:
        return int((time.time() - self.t0) * 1000)

    def log(self, actor: str, action: str, detail: str = "", *, model: str = "",
            status: str = "info", step_id: str | None = None, duration_ms: int = 0, tokens: int = 0) -> str:
        sid = step_id or uuid.uuid4().hex[:10]
        store.docs().append("runs", self.run_id, "steps", {
            "id": sid, "t_ms": self._ms(), "actor": actor, "model": model, "action": action,
            "detail": detail[:600], "status": status, "duration_ms": duration_ms, "tokens": tokens,
        })
        return sid

    @asynccontextmanager
    async def span(self, actor: str, action: str, *, model: str = "", detail: str = ""):
        """Logs a running step, then its outcome. Yields a dict the caller can fill
        with 'detail' and 'tokens'."""
        sid = self.log(actor, action, detail, model=model, status="running")
        start = time.time()
        out = {"detail": detail, "tokens": 0, "status": "ok"}
        try:
            yield out
        except Exception as exc:
            self.log(actor, action, f"{type(exc).__name__}: {exc}", model=model, status="error",
                     step_id=sid, duration_ms=int((time.time() - start) * 1000))
            raise
        self.log(actor, action, out["detail"], model=model, status=out["status"], step_id=sid,
                 duration_ms=int((time.time() - start) * 1000), tokens=out["tokens"])

    def finish(self, error: str = "") -> None:
        store.docs().update("runs", self.run_id, {
            "status": "error" if error else "done", "finished_at": time.time(), "error": error,
        })
