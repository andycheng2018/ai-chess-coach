"""Local registry of the Lichess BOT accounts the coach can play as.

The SQLite database records each account's label, username and a *reference*
to its token, plus which account is selected. Token values never enter the
database, API responses or logs:

* ``env``          the original account from LICHESS_BOT_TOKEN or bot/config.yml
                   (the Android build fills the same variables from Keystore).
* ``env:NAME``     another environment variable, for example LICHESS_BOT_TOKEN_2.
* ``file:<id>``    a 0600 file beside the database, written once when the
                   account is added from the app.

Data lives under CHESS_DATA_HOME (the repository on a Mac, private app storage
on Android), resolved when the store opens so tests can point it elsewhere.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
BOT_CONFIG = ROOT / "bot" / "config.yml"
DEFAULT_ACCOUNT_ID = "default"
DEFAULT_USERNAME = "bot_2435"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$")
TOKEN_ENV_PATTERN = re.compile(r"^LICHESS_[A-Z0-9_]{1,60}$")
ACCOUNT_ID_PATTERN = re.compile(r"^[a-z0-9]{1,32}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    username TEXT NOT NULL,
    token_ref TEXT NOT NULL,
    token_hint TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def token_from_config() -> tuple[str, str]:
    """The original single-account configuration: .env first, then config.yml."""
    env_token = os.getenv("LICHESS_BOT_TOKEN", "").strip()
    env_username = os.getenv("LICHESS_BOT_USERNAME", "").strip()
    if env_token:
        return env_token, env_username
    if not BOT_CONFIG.exists():
        return "", env_username
    try:
        data = yaml.safe_load(BOT_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", env_username
    if not isinstance(data, dict):
        return "", env_username
    return str(data.get("token", "")).strip(), str(data.get("username", env_username or "")).strip()


def is_placeholder(token: str) -> bool:
    upper = token.upper()
    return not token or any(marker in upper for marker in ("PASTE_", "TOKEN_HERE", "YOUR_TOKEN", "XXX"))


def token_hint(token: str) -> str:
    return "" if is_placeholder(token) or len(token) < 8 else token[-4:]


def default_data_home() -> Path:
    return Path(os.environ.get("CHESS_DATA_HOME", ROOT)) / "bot-accounts"


@dataclass(frozen=True)
class BotAccount:
    """A resolved account. The token is kept out of repr so it cannot reach logs."""
    id: str
    label: str
    username: str
    token: str = field(repr=False)
    # The migrated default may not name its username; Lichess then decides it.
    strict_username: bool = True

    def with_username(self, username: str) -> "BotAccount":
        return replace(self, username=username)


class BotAccountStore:
    def __init__(self, directory: Path | str | None = None) -> None:
        """``directory=None`` keeps everything in memory (tests, throwaway runtimes)."""
        self._lock = threading.RLock()
        self._directory = Path(directory) if directory is not None else None
        self._memory_tokens: dict[str, str] = {}
        if self._directory is None:
            self._db = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._directory.mkdir(parents=True, exist_ok=True)
            os.chmod(self._directory, 0o700)
            path = self._directory / "accounts.sqlite3"
            # sqlite creates files with the process umask; make it private first.
            os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
            os.chmod(path, 0o600)
            self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
        self._migrate_default()

    @classmethod
    def open_default(cls) -> "BotAccountStore":
        return cls(default_data_home())

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __del__(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass

    # -- internal helpers -------------------------------------------------
    def _setting(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            self._db.execute("DELETE FROM bot_settings WHERE key = ?", (key,))
        else:
            self._db.execute(
                "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def _rows(self) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT * FROM bot_accounts ORDER BY id = ? DESC, created_at, id", (DEFAULT_ACCOUNT_ID,)).fetchall()

    def _row(self, account_id: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM bot_accounts WHERE id = ?", (account_id,)).fetchone()

    def _token_path(self, account_id: str) -> Path:
        assert self._directory is not None
        return self._directory / "tokens" / f"{account_id}.token"

    def _write_token(self, account_id: str, token: str) -> None:
        if self._directory is None:
            self._memory_tokens[account_id] = token
            return
        path = self._token_path(account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        temporary = path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8",
                  opener=lambda name, flags: os.open(name, flags | os.O_TRUNC, 0o600)) as stream:
            stream.write(token)
        os.replace(temporary, path)

    def _delete_token(self, account_id: str) -> None:
        self._memory_tokens.pop(account_id, None)
        if self._directory is not None:
            try:
                self._token_path(account_id).unlink()
            except FileNotFoundError:
                pass

    def _read_token(self, row: sqlite3.Row) -> str:
        ref = str(row["token_ref"])
        if ref == "env":
            return token_from_config()[0]
        if ref.startswith("env:"):
            return os.getenv(ref[4:], "").strip()
        if ref.startswith("file:"):
            account_id = ref[5:]
            if self._directory is None:
                return self._memory_tokens.get(account_id, "")
            try:
                return self._token_path(account_id).read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def _migrate_default(self) -> None:
        """Seed the original .env/config.yml account so existing setups keep working."""
        with self._lock, self._db:
            if self._setting("default_removed") != "1" and self._row(DEFAULT_ACCOUNT_ID) is None:
                configured = token_from_config()[1] or DEFAULT_USERNAME
                self._db.execute(
                    "INSERT INTO bot_accounts (id, label, username, token_ref, token_hint, created_at) "
                    "VALUES (?, ?, ?, 'env', '', ?)",
                    (DEFAULT_ACCOUNT_ID, "Default (.env)", configured, int(time.time())))
            selected = self._setting("selected_account")
            if selected is None or self._row(selected) is None:
                rows = self._rows()
                self._set_setting("selected_account", rows[0]["id"] if rows else None)

    def _resolve(self, row: sqlite3.Row) -> BotAccount:
        token = self._read_token(row)
        username = str(row["username"])
        strict = True
        if row["token_ref"] == "env":
            configured = token_from_config()[1]
            strict = bool(configured)
            username = configured or username
        return BotAccount(id=str(row["id"]), label=str(row["label"]), username=username,
                          token=token, strict_username=strict)

    def _public(self, row: sqlite3.Row, selected: str | None) -> dict[str, Any]:
        account = self._resolve(row)
        ref = str(row["token_ref"])
        return {
            "id": account.id,
            "label": account.label,
            "username": account.username,
            "tokenSource": "env" if ref.startswith("env") else "saved",
            "tokenEnv": "LICHESS_BOT_TOKEN" if ref == "env" else ref[4:] if ref.startswith("env:") else None,
            "tokenHint": token_hint(account.token),
            "tokenConfigured": not is_placeholder(account.token),
            "selected": account.id == selected,
            "isDefault": account.id == DEFAULT_ACCOUNT_ID,
        }

    # -- public API -------------------------------------------------------
    def list_accounts(self) -> list[dict[str, Any]]:
        with self._lock:
            selected = self._setting("selected_account")
            return [self._public(row, selected) for row in self._rows()]

    def public(self, account_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._row(account_id)
            return self._public(row, self._setting("selected_account")) if row else None

    def selected_id(self) -> str | None:
        with self._lock:
            return self._setting("selected_account")

    def resolve(self, account_id: str | None) -> BotAccount | None:
        if not account_id:
            return None
        with self._lock:
            row = self._row(account_id)
            return self._resolve(row) if row else None

    def selected(self) -> BotAccount | None:
        with self._lock:
            return self.resolve(self._setting("selected_account"))

    def select(self, account_id: str) -> None:
        with self._lock, self._db:
            if self._row(account_id) is None:
                raise ValueError("Unknown bot account.")
            self._set_setting("selected_account", account_id)

    def add(self, *, label: str = "", username: str, token: str = "", token_env: str = "") -> dict[str, Any]:
        username = username.strip()
        label = (label.strip() or username)[:60]
        token = token.strip()
        token_env = token_env.strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("Enter the bot's Lichess username (2-30 letters, digits, _ or -).")
        if bool(token) == bool(token_env):
            raise ValueError("Paste the bot token, or name the environment variable that holds it.")
        if token and (is_placeholder(token) or len(token) < 8 or len(token) > 200 or re.search(r"\s", token)):
            raise ValueError("That does not look like a Lichess API token.")
        if token_env and not TOKEN_ENV_PATTERN.fullmatch(token_env):
            raise ValueError("The environment variable must look like LICHESS_BOT_TOKEN_2.")
        with self._lock, self._db:
            for row in self._rows():
                if self._resolve(row).username.lower() == username.lower():
                    raise ValueError(f"{username} is already in the bot account list.")
            account_id = secrets.token_hex(6)
            ref = f"file:{account_id}" if token else f"env:{token_env}"
            if token:
                self._write_token(account_id, token)
            self._db.execute(
                "INSERT INTO bot_accounts (id, label, username, token_ref, token_hint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, label, username, ref, token_hint(token), int(time.time())))
            if self._setting("selected_account") is None:
                self._set_setting("selected_account", account_id)
            return self._public(self._row(account_id), self._setting("selected_account"))

    def remove(self, account_id: str) -> None:
        with self._lock, self._db:
            row = self._row(account_id)
            if row is None:
                raise ValueError("Unknown bot account.")
            self._db.execute("DELETE FROM bot_accounts WHERE id = ?", (account_id,))
            if row["token_ref"] == "env":
                # Removing the .env account only hides it; the secret stays in .env.
                self._set_setting("default_removed", "1")
            if str(row["token_ref"]).startswith("file:"):
                self._delete_token(account_id)
            if self._setting("selected_account") == account_id:
                rows = self._rows()
                self._set_setting("selected_account", rows[0]["id"] if rows else None)

    def record_username(self, account_id: str, username: str) -> None:
        """Keep Lichess's canonical spelling after a successful token check."""
        with self._lock, self._db:
            self._db.execute("UPDATE bot_accounts SET username = ? WHERE id = ?", (username, account_id))


AccountSource = BotAccountStore | Callable[[], BotAccountStore] | None
