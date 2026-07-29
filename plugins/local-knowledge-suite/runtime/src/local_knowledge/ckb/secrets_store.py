# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import Database


MASTER_KEY_USERNAME = "master-key"


class SecretStoreError(RuntimeError):
    pass


def purge_company_master_key(company_id: str) -> dict[str, object]:
    """Delete only one company's OS-keyring master key, if it exists."""

    from ..manifests import validate_id

    identifier = validate_id(company_id, "company_id")
    service_name = f"local-knowledge-suite/{identifier}"
    try:
        import keyring

        encoded = keyring.get_password(service_name, MASTER_KEY_USERNAME)
        if encoded is None:
            return {
                "service": service_name,
                "username": MASTER_KEY_USERNAME,
                "deleted": False,
                "missing": True,
            }
        keyring.delete_password(service_name, MASTER_KEY_USERNAME)
        return {
            "service": service_name,
            "username": MASTER_KEY_USERNAME,
            "deleted": True,
            "missing": False,
        }
    except Exception as exc:
        raise SecretStoreError(f"OS keyring credential purge failed: {exc}") from exc


class SecretStore:
    def __init__(
        self,
        db: Database,
        service_name: str,
        key_provider: Callable[[bool], bytes | None] | None = None,
    ) -> None:
        self.db = db
        self.service_name = service_name
        self._key_provider = key_provider or self._keyring_key

    def _keyring_key(self, create: bool) -> bytes | None:
        try:
            import keyring

            encoded = keyring.get_password(self.service_name, MASTER_KEY_USERNAME)
            if encoded:
                return base64.urlsafe_b64decode(encoded.encode("ascii"))
            if not create:
                return None
            key = AESGCM.generate_key(bit_length=256)
            keyring.set_password(
                self.service_name,
                MASTER_KEY_USERNAME,
                base64.urlsafe_b64encode(key).decode("ascii"),
            )
            return key
        except Exception as exc:
            raise SecretStoreError(f"OS keyring is unavailable: {exc}") from exc

    @staticmethod
    def _where_owner(owner_user_id: int | None) -> tuple[str, tuple[object, ...]]:
        return ("owner_user_id IS NULL", ()) if owner_user_id is None else ("owner_user_id=?", (owner_user_id,))

    def set(self, name: str, value: str, owner_user_id: int | None = None) -> None:
        if not name or not value:
            raise ValueError("secret name and value are required")
        key = self._key_provider(True)
        if key is None:
            raise SecretStoreError("encryption key is unavailable")
        nonce = secrets.token_bytes(12)
        aad = f"{owner_user_id or 'global'}:{name}".encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), aad)
        owner_clause, owner_params = self._where_owner(owner_user_id)
        now = datetime.now(UTC).isoformat()
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute(
                f"SELECT id FROM secret_records WHERE {owner_clause} AND name=?",
                (*owner_params, name),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE secret_records SET ciphertext=?,nonce=?,updated_at=? WHERE id=?",
                    (ciphertext, nonce, now, row["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO secret_records(owner_user_id,name,ciphertext,nonce,updated_at) VALUES(?,?,?,?,?)",
                    (owner_user_id, name, ciphertext, nonce, now),
                )

    def get(self, name: str, owner_user_id: int | None = None) -> str | None:
        owner_clause, owner_params = self._where_owner(owner_user_id)
        with self.db.connect() as connection:
            row = connection.execute(
                f"SELECT ciphertext,nonce FROM secret_records WHERE {owner_clause} AND name=?",
                (*owner_params, name),
            ).fetchone()
        if row is None:
            return None
        key = self._key_provider(False)
        if key is None:
            raise SecretStoreError("OS keyring is locked or the encryption key is missing")
        aad = f"{owner_user_id or 'global'}:{name}".encode("utf-8")
        try:
            plaintext = AESGCM(key).decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]), aad)
        except Exception as exc:
            raise SecretStoreError("secret could not be decrypted") from exc
        return plaintext.decode("utf-8")

    def delete(self, name: str, owner_user_id: int | None = None) -> bool:
        owner_clause, owner_params = self._where_owner(owner_user_id)
        with self.db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"DELETE FROM secret_records WHERE {owner_clause} AND name=?",
                (*owner_params, name),
            )
            return cursor.rowcount == 1

    def status(self, owner_user_id: int | None = None) -> list[dict[str, object]]:
        owner_clause, owner_params = self._where_owner(owner_user_id)
        with self.db.connect() as connection:
            rows = connection.execute(
                f"SELECT name,created_at,updated_at FROM secret_records WHERE {owner_clause} ORDER BY name",
                owner_params,
            ).fetchall()
        return [{"name": row["name"], "configured": True, "created_at": row["created_at"], "updated_at": row["updated_at"]} for row in rows]

    def health(self) -> dict[str, object]:
        with self.db.connect() as connection:
            configured = int(connection.execute("SELECT COUNT(*) FROM secret_records").fetchone()[0])
        try:
            import keyring

            backend = keyring.get_keyring()
            available = bool(getattr(backend, "priority", 0) > 0)
            return {"available": available, "backend": backend.__class__.__name__, "configured": configured}
        except Exception as exc:
            return {"available": False, "configured": configured, "error": str(exc)}

    def set_json(self, name: str, value: dict[str, str], owner_user_id: int | None = None) -> None:
        self.set(name, json.dumps(value, separators=(",", ":")), owner_user_id)

    def get_json(self, name: str, owner_user_id: int | None = None) -> dict[str, str] | None:
        value = self.get(name, owner_user_id)
        return json.loads(value) if value else None
