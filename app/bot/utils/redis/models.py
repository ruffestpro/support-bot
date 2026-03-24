from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta


def _default_created_at() -> str:
    """Время создания записи на момент создания объекта (не при импорте модуля)."""
    return datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S %Z")


@dataclass
class UserData:
    """Data class representing user information."""
    message_thread_id: int | None
    message_silent_id: int | None
    message_silent_mode: bool

    id: int
    full_name: str
    username: str | None
    state: str = "member"
    is_banned: bool = False
    language_code: str | None = None
    created_at: str = field(default_factory=_default_created_at)

    def to_dict(self) -> dict:
        """
        Converts UserData object to a dictionary.

        :return: Dictionary representation of UserData.
        """
        return asdict(self)
