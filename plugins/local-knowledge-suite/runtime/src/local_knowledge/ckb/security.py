# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .db import Database


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(db: Database, username: str, password: str, role: str) -> int:
    if role not in {"admin", "reviewer", "reader"}:
        raise ValueError("invalid role")
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    with db.transaction(immediate=True) as connection:
        cursor = connection.execute(
            "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
            (username, PASSWORD_HASHER.hash(password), role),
        )
        user_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT OR IGNORE INTO branch_members(branch_id,user_id,role) SELECT id,?,? FROM branches WHERE is_canonical=1",
            (user_id, role),
        )
        return user_id


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def authenticate(db: Database, username: str, password: str) -> dict[str, object] | None:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT id,username,password_hash,role,active FROM users WHERE username=?",
            (username,),
        ).fetchone()
    if row is None or not row["active"] or not verify_password(row["password_hash"], password):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def create_session(db: Database, user_id: int, hours: int) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=hours)
    with db.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
            (_token_hash(token), user_id, csrf, expires.isoformat()),
        )
    return token, csrf, expires.isoformat()


def get_session_user(db: Database, token: str | None) -> dict[str, object] | None:
    if not token:
        return None
    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT u.id,u.username,u.role,s.csrf_token,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND u.active=1
            """,
            (_token_hash(token),),
        ).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        return None
    return dict(row)


def delete_session(db: Database, token: str | None) -> None:
    if not token:
        return
    with db.transaction(immediate=True) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def purge_expired_sessions(db: Database) -> int:
    with db.transaction(immediate=True) as connection:
        cursor = connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (datetime.now(UTC).isoformat(),))
        return cursor.rowcount
