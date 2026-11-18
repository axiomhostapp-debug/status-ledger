"""Persistent incident history for a fictional hosting service."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from migrations import migrate

STATES = ("investigating", "identified", "monitoring", "resolved")
NEXT = {"investigating": {"identified", "resolved"},
        "identified": {"monitoring", "resolved"},
        "monitoring": {"identified", "resolved"}, "resolved": set()}


class Conflict(ValueError):
    """The incident changed since the caller last read it."""


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            migrate(self.db)
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @staticmethod
    def _text(value, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"text must be nonempty and at most {limit} characters")
        return value.strip()

    def create(self, service, title, message):
        service, title, message = (self._text(service, 80), self._text(title, 160),
                                   self._text(message, 2000))
        key = uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO incidents VALUES (?, ?, ?, 'investigating', 1)",
                            (key, service, title))
            self._event(key, "investigating", message)
        return self.get(key)

    def _event(self, key, state, message):
        self.db.execute("INSERT INTO events(incident_id,state,message,at) VALUES (?,?,?,?)",
                        (key, state, message, datetime.now(timezone.utc).isoformat()))

    @contextmanager
    def snapshot(self):
        """Keep related reads consistent; reuse an enclosing write transaction."""
        if self.db.in_transaction:
            yield
        else:
            with self.db:
                self.db.execute("BEGIN")
                yield

    def get(self, key):
        with self.snapshot():
            return self._get(key)

    def _get(self, key):
        row = self.db.execute("SELECT * FROM incidents WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError("incident not found")
        result = dict(row)
        result["events"] = [dict(e) for e in self.db.execute(
            "SELECT state,message,at FROM events WHERE incident_id=? ORDER BY sequence", (key,))]
        return result

    def transition(self, key, state, message, expected_version):
        message = self._text(message, 2000)
        if state not in STATES:
            raise ValueError("unknown state")
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        # Serialize read-check-write so concurrent writers cannot lose an update.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            current = self.get(key)
            if current["version"] != expected_version:
                raise Conflict("stale incident version")
            if state not in NEXT[current["state"]]:
                raise ValueError("invalid state transition")
            self.db.execute("UPDATE incidents SET state=?,version=version+1 WHERE id=?", (state, key))
            self._event(key, state, message)
        return self.get(key)

    def status(self):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM incidents ORDER BY rowid DESC")]
        return {"status": "degraded" if any(r["state"] != "resolved" for r in rows) else "operational",
                "incidents": rows}

    def publish_notice(self, service, title, message):
        """Record information only; notices never modify incident or service state."""
        notice = dict(id=uuid4().hex, service=self._text(service, 80),
                      title=self._text(title, 160), message=self._text(message, 2000),
                      published_at=datetime.now(timezone.utc).isoformat())
        with self.db:
            self.db.execute("INSERT INTO notices VALUES (:id,:service,:title,:message,:published_at)", notice)
        return notice

    def notices(self):
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM notices ORDER BY published_at DESC, rowid DESC")]
