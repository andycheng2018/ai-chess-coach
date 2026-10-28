"""One append-only journal for model attempts and player learning records."""
from __future__ import annotations

import json
import os
import threading
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class CoachHistory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()

    def entries(self) -> list[dict[str, Any]]:
        with self.lock:
            if not self.path.is_file():
                return []
            entries = []
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        entries.append(value)
                except json.JSONDecodeError:
                    # Old/truncated lines must not hide the remaining history.
                    continue
            return entries

    def append(self, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                # Repair a truncated tail before appending the next event.
                if self.path.stat().st_size:
                    with self.path.open("rb") as reader:
                        reader.seek(-1, os.SEEK_END)
                        if reader.read(1) != b"\n":
                            stream.write("\n")
                for entry in entries:
                    stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def session(self, game_id: str) -> list[dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        for entry in self.entries():
            if entry.get("event") == "learning_record" and entry.get("game_id") == game_id:
                record = entry.get("record", {})
                if isinstance(record.get("ply"), int):
                    records[record["ply"]] = record
        return sorted(records.values(), key=lambda record: record["ply"])

    def save_records(self, game_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not game_id:
            raise ValueError("gameId is required")
        with self.lock:
            current = {record["ply"]: record for record in self.session(game_id)}
            changes = []
            for supplied in records:
                if not isinstance(supplied, dict) or not isinstance(supplied.get("ply"), int):
                    raise ValueError("Each history record requires an integer ply")
                if not supplied.get("fenBefore") or not supplied.get("playedMoveUci"):
                    raise ValueError("Each history record requires fenBefore and playedMoveUci")
                record = {**supplied, "gameId": game_id}
                record.setdefault("recordId", record.get("analysisId") or uuid.uuid4().hex)
                old = current.get(record["ply"])
                if old:
                    same_move = (old.get("fenBefore"), old.get("playedMoveUci")) == (
                        record["fenBefore"], record["playedMoveUci"]
                    )
                    if same_move:
                        # A delayed cache upload must not erase accepted wording.
                        if old.get("explanationPending") is False and record.get("explanationPending") is True:
                            record = {**record, **old}
                        elif old.get("explanationPending") is True and record.get("explanationPending") is False:
                            record = {**old, **record}
                        elif (old.get("savedAt") or 0) > (record.get("savedAt") or 0):
                            record = {**record, **old}
                        else:
                            record = {**old, **record}
                    elif (old.get("savedAt") or 0) > (record.get("savedAt") or 0):
                        continue
                if record == old:
                    continue
                current[record["ply"]] = record
                changes.append({
                    "event": "learning_record", "timestamp": timestamp(),
                    "game_id": game_id, "record_id": record["recordId"], "record": record,
                })
            self.append(changes)
            return sorted(current.values(), key=lambda record: record["ply"])

    def audit_entries(self) -> list[dict[str, Any]]:
        """Project the same learning records onto attempts without duplicating them."""
        entries = self.entries()
        records = {
            (entry.get("game_id"), entry.get("record_id")): entry["record"]
            for entry in entries if entry.get("event") == "learning_record"
        }
        positions: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for record in records.values():
            position = (record.get("gameId", ""), record.get("fenBefore", ""), record.get("playedMoveUci", ""))
            positions.setdefault(position, []).append(record)
        attempts = [entry for entry in entries if entry.get("event") != "learning_record"]
        linked = set()
        result = []
        for attempt in attempts:
            key = (attempt.get("game_id"), attempt.get("record_id"))
            record = records.get(key)
            if record is None and not attempt.get("record_id") and attempt.get("type") == "feedback":
                payload = attempt.get("payload") or {}
                position = (attempt.get("game_id", ""), payload.get("fen_before", ""),
                            attempt.get("played_move_uci") or payload.get("played_move_uci", ""))
                candidates = positions.get(position, [])
                # Older logs omitted IDs. Link only an unambiguous exact game/position/move.
                if all(position) and len(candidates) == 1:
                    record = candidates[0]
                    key = (record["gameId"], record["recordId"])
                    attempt = {**attempt, "record_id": record["recordId"], "link_source": "legacy_position"}
            result.append({**attempt, **({"learning_record": record} if record else {})})
            if record:
                linked.add(key)
        # Imported notes and engine-only records are reviewable in Audit Studio too.
        for key, record in records.items():
            if key in linked:
                continue
            result.append({
                "event": "learning_record", "type": "feedback", "game_id": key[0],
                "record_id": key[1], "timestamp": datetime.fromtimestamp(
                    (record.get("savedAt") or 0) / 1000, timezone.utc
                ).isoformat(),
                "move_number": record.get("moveNumber"), "played_move": record.get("playedMove"),
                "played_move_uci": record.get("playedMoveUci"),
                "classification": record.get("classification"),
                "centipawn_loss": record.get("centipawnLoss"),
                "status": "success", "learning_record": record,
                "model": "No recorded model attempt",
                "payload": {"fen_before": record.get("fenBefore"), "fen_after": record.get("fenAfter"),
                            "best_move": record.get("bestMove"), "best_move_uci": record.get("bestMoveUci"),
                            "classification": record.get("classification"), "best_line": record.get("bestLine", [])},
            })
        return sorted(result, key=lambda entry: entry.get("timestamp", ""))

    def clear_attempts(self) -> None:
        """Clearing audit data preserves player review records in the shared journal."""
        with self.lock:
            records = [entry for entry in self.entries() if entry.get("event") == "learning_record"]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)


history = CoachHistory(Path(__file__).resolve().parents[2] / "logs" / "coach_logs.jsonl")
_call: ContextVar[dict[str, Any] | None] = ContextVar("coach_audit_call", default=None)


def record_attempt(entry: dict[str, Any]) -> None:
    call = _call.get()
    if call is None:
        raise RuntimeError("Model attempts require an audited coaching call")
    call["attempts"].append({**entry, "attempt_id": uuid.uuid4().hex})


def audit_call(kind: str):
    """Keep raw drafts, validation failures, and the accepted wording together."""
    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            record_id = kwargs.get("record_id") or uuid.uuid4().hex
            call: dict[str, Any] = {"attempts": []}
            token = _call.set(call)
            output = None
            error = None
            try:
                output = function(self, *args, **kwargs)
                return {**output, "recordId": record_id}
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                _call.reset(token)
                entries = []
                for index, attempt in enumerate(call["attempts"]):
                    entries.append({
                        **attempt, "event": "model_attempt", "type": kind,
                        "record_id": record_id, "attempt_number": index + 1,
                        "outcome": "accepted" if output is not None and index == len(call["attempts"]) - 1 else "rejected",
                        **({"final_output": output} if output is not None and index == len(call["attempts"]) - 1 else {}),
                        **({"validation_error": error} if error else {}),
                    })
                history.append(entries)
        return wrapped
    return decorate
