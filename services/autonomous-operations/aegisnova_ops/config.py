"""Configuration (env-driven, safe defaults)."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    max_attempts: int = 3
    max_retry_window_s: int = 3600
    max_receive_count: int = 5
    lease_s: int = 60
    step_timeout_s: float = 30
    queue_max_depth: int = 1000
    concurrency: int = 4
    notif_max_attempts: int = 4
    notif_max_window_s: int = 3600
    notif_stale_sending_s: int = 120
    notify_rate_per_min: int = 30
    breaker_threshold: int = 3
    breaker_cooldown_s: int = 60
    storm_limit: int = 5
    storm_window_s: int = 300
    redrive_max_per_call: int = 10
    redrive_max_per_hour: int = 50
    redrive_loop_limit: int = 3
    stuck_run_s: int = 900
    heartbeat_stale_s: int = 30
    retention_days: int = 30
    worker_interval_s: float = 1.0

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        c = cls()
        for f in c.__dataclass_fields__:
            v = env.get("AEGIS_" + f.upper())
            if v is not None:
                cur = getattr(c, f)
                setattr(c, f, type(cur)(v))
        return c
