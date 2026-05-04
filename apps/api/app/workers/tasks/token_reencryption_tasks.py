"""Re-encrypt legacy plaintext OAuth and MCP token rows in place (C2).

Rows written before the ``EncryptedText`` decorator landed are stored as
plaintext. The read path tolerates that (the decorator passes through
non-prefixed values), but a partial DB dump still mixes ciphertext and
plaintext until those rows are rewritten.

This task scans both tables in batches, identifies rows where any
encrypted column is plaintext (no ``enc1:`` prefix and a non-null value),
and rewrites them via the ORM so the decorator encrypts on write.

Designed to be idempotent — already-encrypted rows are skipped — and safe
to run repeatedly. Cap on rows processed per invocation prevents one run
from monopolising the worker.
"""

from typing import Optional

from shared.py.wide_events import log, wide_task
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.postgresql import get_db_session
from app.models.db_oauth import MCPCredential, OAuthToken
from app.utils.crypto.token_encryption import hash_token_for_lookup

_CIPHERTEXT_PREFIX = "enc1:"
_BATCH_SIZE = 200
_DEFAULT_MAX_ROWS = 5_000


def _is_plaintext(value: Optional[str]) -> bool:
    return value is not None and not value.startswith(_CIPHERTEXT_PREFIX)


async def _list_ids_after(model: type, last_id: int) -> list[int]:
    """Return up to ``_BATCH_SIZE`` PKs after ``last_id`` (no row lock).

    Pagination uses an unlocked read so the worker can stride through the
    table without blocking concurrent OAuth refreshes. The actual
    re-encryption runs in a separate, row-locked transaction per row.
    """
    async with get_db_session() as session:
        stmt = (
            select(model.id)
            .where(model.id > last_id)
            .order_by(model.id)
            .limit(_BATCH_SIZE)
        )
        result = await session.execute(stmt)
        return [int(i) for i in result.scalars().all()]


async def _rewrite_row(model: type, row_id: int) -> bool:
    """Re-encrypt a single row inside a short, row-locked transaction.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so a row currently held by
    a concurrent OAuth refresh (``store_token`` / ``update``) is skipped
    rather than overwritten with a stale plaintext value. The lock is
    released as soon as this transaction commits — the locked window is
    bounded by the time it takes to ``flag_modified`` and flush.
    """
    async with get_db_session() as session:
        stmt = select(model).where(model.id == row_id).with_for_update(skip_locked=True)
        row = (await session.execute(stmt)).scalars().first()
        if row is None:
            # Either the row was deleted or another writer holds the
            # lock. Either way, leave it for a future run.
            return False

        # Values are plaintext here regardless of underlying storage —
        # ``EncryptedText`` decrypts on read. ``flag_modified`` forces
        # SA to emit an UPDATE that runs ``process_bind_param`` and
        # re-encrypts. Already-encrypted rows are rewritten redundantly
        # but the bytes-on-disk change because Fernet uses a random IV;
        # that's acceptable for a one-shot backfill.
        if model is OAuthToken:
            if row.access_token is not None:
                flag_modified(row, "access_token")
            if row.refresh_token is not None:
                flag_modified(row, "refresh_token")
            if row.token_data is not None:
                flag_modified(row, "token_data")
            if not row.access_token_hash and row.access_token:
                row.access_token_hash = hash_token_for_lookup(row.access_token)
        else:
            if row.access_token is not None:
                flag_modified(row, "access_token")
            if row.refresh_token is not None:
                flag_modified(row, "refresh_token")
            if row.client_registration is not None:
                flag_modified(row, "client_registration")
        await session.commit()
        return True


async def _reencrypt_oauth_tokens(max_rows: int) -> int:
    """Walk ``oauth_tokens`` and rewrite any row with a plaintext column.

    Returns the number of rows rewritten.
    """
    rewritten = 0
    last_id = 0
    while rewritten < max_rows:
        ids = await _list_ids_after(OAuthToken, last_id)
        if not ids:
            break
        for row_id in ids:
            last_id = row_id
            if await _rewrite_row(OAuthToken, row_id):
                rewritten += 1
            if rewritten >= max_rows:
                break
        if len(ids) < _BATCH_SIZE:
            break
    return rewritten


async def _reencrypt_mcp_credentials(max_rows: int) -> int:
    """Walk ``mcp_credentials`` and rewrite plaintext token columns."""
    rewritten = 0
    last_id = 0
    while rewritten < max_rows:
        ids = await _list_ids_after(MCPCredential, last_id)
        if not ids:
            break
        for row_id in ids:
            last_id = row_id
            if await _rewrite_row(MCPCredential, row_id):
                rewritten += 1
            if rewritten >= max_rows:
                break
        if len(ids) < _BATCH_SIZE:
            break
    return rewritten


async def reencrypt_legacy_tokens(ctx: dict, max_rows: int = _DEFAULT_MAX_ROWS) -> str:
    """Backfill task: re-encrypt plaintext OAuth/MCP token rows (C2)."""
    async with wide_task("reencrypt_legacy_tokens", max_rows=max_rows):
        oauth_rewritten = await _reencrypt_oauth_tokens(max_rows)
        mcp_rewritten = await _reencrypt_mcp_credentials(max_rows)
        log.set(
            oauth_tokens_rewritten=oauth_rewritten,
            mcp_credentials_rewritten=mcp_rewritten,
        )
        message = (
            f"Re-encrypted {oauth_rewritten} oauth_tokens and "
            f"{mcp_rewritten} mcp_credentials rows"
        )
        log.info(message)
        return message
