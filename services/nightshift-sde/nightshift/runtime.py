"""Local execution mode: scheduler, watchdog and worker threads inside one process.

State is never held here — every thread just drives the database-backed components, so killing the process at any
instant is safe: on restart the watchdog reclaims expired leases, the scheduler applies each schedule's missed-run
policy, and jobs resume from their last valid checkpoint.
"""
from __future__ import annotations

import logging
import threading

from .service import App
from .worker import Worker

log = logging.getLogger("nightshift.runtime")


class Runtime:
    def __init__(self, app: App, *, workers: int = 1, scheduler: bool = True, watchdog: bool = True):
        self.app, self.n_workers, self.run_scheduler, self.run_watchdog = app, workers, scheduler, watchdog
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        a = self.app
        if self.run_watchdog:
            a.watchdog.tick()  # startup recovery: reclaim expired leases left by a previous process
        if self.run_scheduler:
            a.scheduler.tick()  # startup: apply missed-run policy immediately
        for i in range(self.n_workers):
            w = Worker(a.store, a.settings, a.runner, a.gov, a.sandbox, a.notifier)
            self._spawn(f"ns-worker-{i}", lambda w=w: w.run_forever(self.stop_event))
        if self.run_scheduler:
            self._spawn("ns-scheduler", lambda: self._loop(a.scheduler.tick, a.settings.scheduler_tick_seconds, "scheduler"))
        if self.run_watchdog:
            self._spawn("ns-watchdog", lambda: self._loop(self._watch, a.settings.watchdog_interval_seconds, "watchdog"))

    def _watch(self) -> None:
        self.app.watchdog.tick()
        self.app.notifier.dispatch_pending()

    def _loop(self, fn, interval: float, name: str) -> None:
        while not self.stop_event.wait(interval):
            try:
                fn()
            except Exception:  # noqa: BLE001 — a failed tick must not kill the loop; the next tick retries
                log.exception("%s tick failed", name)

    def _spawn(self, name: str, target) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=timeout)
