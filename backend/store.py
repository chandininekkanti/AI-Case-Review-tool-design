"""
Tiny persistence layer for investigator actions: decision (accept/reject),
notes, and chat history per case. Backed by a single JSON file so the
prototype needs no database, but survives server restarts (useful for a demo).
"""
import json
import threading
from pathlib import Path

_LOCK = threading.Lock()


class CaseStore:
    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text("{}")

    def _read(self) -> dict:
        with _LOCK:
            return json.loads(self.path.read_text() or "{}")

    def _write(self, data: dict):
        with _LOCK:
            self.path.write_text(json.dumps(data, indent=2))

    def get(self, case_id: str) -> dict:
        return self._read().get(case_id, {
            "decision": "pending",   # pending | accepted | rejected
            "notes": [],
            "chat_history": [],
        })

    def set_decision(self, case_id: str, decision: str):
        data = self._read()
        entry = data.setdefault(case_id, {"decision": "pending", "notes": [], "chat_history": []})
        entry["decision"] = decision
        self._write(data)
        return entry

    def add_note(self, case_id: str, note: str):
        data = self._read()
        entry = data.setdefault(case_id, {"decision": "pending", "notes": [], "chat_history": []})
        entry["notes"].append(note)
        self._write(data)
        return entry

    def append_chat(self, case_id: str, role: str, content: str):
        data = self._read()
        entry = data.setdefault(case_id, {"decision": "pending", "notes": [], "chat_history": []})
        entry["chat_history"].append({"role": role, "content": content})
        self._write(data)
        return entry
