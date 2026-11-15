import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    token: str | None = None
    data_file: Path = Path("user_data.json")
    admin_chat_id: str | None = None
    check_interval: tuple[float, float] = (240.0, 360.0)
    startup_stagger: tuple[float, float] = (5.0, 30.0)
    page_pause: tuple[float, float] = (3.0, 6.0)
    baseline_max_pages: int = 5
    check_max_pages: int = 3
    flood_cap: int = 10
    retry_delays: tuple[float, ...] = (60.0, 300.0, 900.0)
    baseline_failures_before_notice: int = 3
    check_failures_before_notice: int = 4
    admin_alert_after_failures: int = 6
    seen_retention_days: int = 30

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            token=env.get("TELEGRAM_TOKEN") or None,
            data_file=Path(env.get("ZONABOT_DATA_FILE") or "user_data.json"),
            admin_chat_id=env.get("ADMIN_CHAT_ID") or None,
        )
