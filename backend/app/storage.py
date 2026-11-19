import json
import sqlite3
import threading
from datetime import datetime, timezone


class AuditStore:
    def __init__(self, path: str = ""):
        self.lock = threading.Lock()
        self.data = {}
        self.conn = sqlite3.connect(path, check_same_thread=False) if path else None
        if self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            self.conn.commit()

    def save(self, audit: dict) -> dict:
        with self.lock:
            self.data[audit["id"]] = audit
            if self.conn:
                self.conn.execute("INSERT OR REPLACE INTO audits VALUES (?, ?)", (audit["id"], json.dumps(audit)))
                self.conn.commit()
        return audit

    def all(self) -> list[dict]:
        with self.lock:
            if self.conn:
                return [json.loads(row[0]) for row in self.conn.execute("SELECT payload FROM audits ORDER BY rowid DESC")]
            return list(reversed(list(self.data.values())))

    def get(self, audit_id: str):
        with self.lock:
            if audit_id in self.data:
                return self.data[audit_id]
            if self.conn:
                row = self.conn.execute("SELECT payload FROM audits WHERE id=?", (audit_id,)).fetchone()
                return json.loads(row[0]) if row else None
            return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
