import contextvars
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


@dataclass(frozen=True)
class LogContext:
    guild_id: int | None = None


current_log_context: contextvars.ContextVar[LogContext] = contextvars.ContextVar(
    "current_log_context", default=LogContext()
)


class GuildLogContext:
    def __init__(self, guild_id: int | None) -> None:
        self._guild_id = guild_id
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "GuildLogContext":
        self._token = current_log_context.set(LogContext(guild_id=self._guild_id))
        return self

    def __exit__(self, *exc: object) -> None:
        if self._token is not None:
            current_log_context.reset(self._token)


def guild_log_context(guild_id: int | None) -> GuildLogContext:
    return GuildLogContext(guild_id)


class NewestFirstFileHandler(logging.Handler):
    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_bytes: int = 1_000_000,
        backup_count: int = 10,
    ) -> None:
        super().__init__()
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._backup_count = backup_count

    def _prepend(self, line: str) -> None:
        old = self._path.read_text(encoding="utf-8") if self._path.exists() else ""
        self._path.write_text(line + old, encoding="utf-8")

    def _rotate_if_needed(self) -> None:
        if self._path.stat().st_size <= self._max_bytes:
            return

        for i in range(self._backup_count - 1, 0, -1):
            src = self._path.with_name(f"{self._path.name}.{i}")
            dst = self._path.with_name(f"{self._path.name}.{i + 1}")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)

        first = self._path.with_name(f"{self._path.name}.1")
        if first.exists():
            first.unlink()
        self._path.rename(first)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._prepend(self.format(record) + "\n")
            self._rotate_if_needed()
        except Exception:
            self.handleError(record)


class PerGuildFileHandler(logging.Handler):
    def __init__(
        self,
        data_dir: str,
        *,
        level: int = logging.DEBUG,
        max_bytes: int = 1_000_000,
        backup_count: int = 10,
    ) -> None:
        super().__init__(level)
        self._log_dir = Path(data_dir) / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handlers: dict[int | None, NewestFirstFileHandler] = {}
        self._handlers_lock = threading.RLock()
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    def _handler_for(self, guild_id: int | None) -> NewestFirstFileHandler:
        with self._handlers_lock:
            handler = self._handlers.get(guild_id)
            if handler is not None:
                return handler

            name = "bot.log" if guild_id is None else f"guild_{guild_id}.log"
            handler = NewestFirstFileHandler(
                self._log_dir / name,
                max_bytes=self._max_bytes,
                backup_count=self._backup_count,
            )
            handler.setLevel(self.level)
            handler.setFormatter(self.formatter)
            self._handlers[guild_id] = handler
            return handler

    def emit(self, record: logging.LogRecord) -> None:
        guild_id = current_log_context.get().guild_id
        handler = self._handler_for(guild_id)
        handler.handle(record)

    def close(self) -> None:
        with self._handlers_lock:
            for handler in self._handlers.values():
                handler.close()
            self._handlers.clear()
        super().close()


def parse_log_level(raw: str | None, default: str = "DEBUG") -> int:
    return LOG_LEVELS.get((raw or default).strip().upper(), LOG_LEVELS[default])


class ErrorFileHandler(NewestFirstFileHandler):
    def __init__(
        self,
        data_dir: str,
        *,
        max_bytes: int = 1_000_000,
        backup_count: int = 10,
    ) -> None:
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            log_dir / "errors.log",
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
        self.setLevel(logging.ERROR)
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))


def setup_dev_logging(data_dir: str, level: int = logging.DEBUG) -> logging.Logger:
    root = logging.getLogger("eradicateur_bot")
    root.setLevel(level)

    existing = [h for h in root.handlers if isinstance(h, PerGuildFileHandler)]
    if not existing:
        handler = PerGuildFileHandler(os.path.join(data_dir, "logs"), level=level)
        root.addHandler(handler)

    existing_errors = [h for h in root.handlers if isinstance(h, ErrorFileHandler)]
    if not existing_errors:
        root.addHandler(ErrorFileHandler(data_dir))

    return root


def set_console_level(level: int) -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(level)
