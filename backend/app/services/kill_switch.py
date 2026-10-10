"""
Global kill switch.

Persisted in SQLite so it survives backend restarts.

When active:
    - /paper/open       -> 403 Forbidden
    - auto trading      -> forced off
    - /paper/close      -> STILL ALLOWED (you must always be able to exit)
    - /paper/update     -> STILL ALLOWED
"""

import datetime
import threading
from typing import Optional

from .storage import Storage
from ..core.logging_setup import get_logger, kv

log = get_logger("kill")


class KillSwitch:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._lock = threading.Lock()
        self._ensure_row()
        self._active, self._reason, self._since = self._load()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _ensure_row(self) -> None:
        with self.storage._lock:
            self.storage._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kill_switch (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    active INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    since TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.storage._conn.execute(
                """
                INSERT OR IGNORE INTO kill_switch
                (id, active, reason, since, updated_at)
                VALUES (1, 0, NULL, NULL, ?)
                """,
                (datetime.datetime.utcnow().isoformat(),),
            )
            self.storage._conn.commit()

    def _load(self) -> tuple[bool, Optional[str], Optional[str]]:
        with self.storage._lock:
            cur = self.storage._conn.execute(
                "SELECT active, reason, since FROM kill_switch WHERE id = 1"
            )
            row = cur.fetchone()
            if row is None:
                return False, None, None
            return bool(row["active"]), row["reason"], row["since"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        return self._active

    def get_state(self) -> dict:
        return {
            "active": self._active,
            "reason": self._reason,
            "since": self._since,
        }

    def trigger(self, reason: str = "MANUAL_EMERGENCY_STOP") -> dict:
        with self._lock:
            now = datetime.datetime.utcnow().isoformat()
            with self.storage._lock:
                self.storage._conn.execute(
                    """
                    UPDATE kill_switch
                    SET active = 1, reason = ?, since = ?, updated_at = ?
                    WHERE id = 1
                    """,
                    (reason, now, now),
                )
                self.storage._conn.commit()

            self._active = True
            self._reason = reason
            self._since = now

            log.warning("kill switch ACTIVATED %s", kv(reason=reason, since=now))

            return self.get_state()

    def release(self) -> dict:
        with self._lock:
            now = datetime.datetime.utcnow().isoformat()
            with self.storage._lock:
                self.storage._conn.execute(
                    """
                    UPDATE kill_switch
                    SET active = 0, reason = NULL, since = NULL, updated_at = ?
                    WHERE id = 1
                    """,
                    (now,),
                )
                self.storage._conn.commit()

            self._active = False
            self._reason = None
            self._since = None

            log.warning("kill switch RELEASED")

            return self.get_state()