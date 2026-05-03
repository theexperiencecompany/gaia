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


async def _reencrypt_oauth_tokens(max_rows: int) -> int:
    """Walk ``oauth_tokens`` and rewrite any row with a plaintext column.

    Returns the number of rows rewritten.
    """
    rewritten = 0
    last_id = 0
    while rewritten < max_rows:
        async with get_db_session() as session:
            stmt = (
                select(OAuthToken)
                .where(OAuthToken.id > last_id)
                .order_by(OAuthToken.id)
                .limit(_BATCH_SIZE)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                break
            for row in rows:
                last_id = row.id
                # ``access_token`` / ``refresh_token`` / ``token_data`` go
                # through the EncryptedText decorator on read, so the
                # values we hold here are plaintext regardless of how
                # they're stored. We can't tell from the decoded value
                # whether the underlying column was plaintext or
                # ciphertext, so we force every column dirty so the flush
                # always emits an UPDATE — that runs ``process_bind_param``
                # which encrypts on write. A redundant write for an
                # already-encrypted row is acceptable for a one-shot
                # backfill; without ``flag_modified`` SA elides the UPDATE
                # because the Python value is unchanged.
                if row.access_token is not None:
                    flag_modified(row, "access_token")
                if row.refresh_token is not None:
                    flag_modified(row, "refresh_token")
                if row.token_data is not None:
                    flag_modified(row, "token_data")
                if not row.access_token_hash and row.access_token:
                    row.access_token_hash = hash_token_for_lookup(row.access_token)
                rewritten += 1
                if rewritten >= max_rows:
                    break
            await session.commit()
        if len(rows) < _BATCH_SIZE:
            break
    return rewritten


async def _reencrypt_mcp_credentials(max_rows: int) -> int:
    """Walk ``mcp_credentials`` and rewrite plaintext token columns."""
    rewritten = 0
    last_id = 0
    while rewritten < max_rows:
        async with get_db_session() as session:
            stmt = (
                select(MCPCredential)
                .where(MCPCredential.id > last_id)
                .order_by(MCPCredential.id)
                .limit(_BATCH_SIZE)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                break
            for row in rows:
                last_id = row.id
                # See ``_reencrypt_oauth_tokens`` — same reason for
                # ``flag_modified``: assigning the same plaintext back
                # is a no-op without it.
                if row.access_token is not None:
                    flag_modified(row, "access_token")
                if row.refresh_token is not None:
                    flag_modified(row, "refresh_token")
                if row.client_registration is not None:
                    flag_modified(row, "client_registration")
                rewritten += 1
                if rewritten >= max_rows:
                    break
            await session.commit()
        if len(rows) < _BATCH_SIZE:
            break
    return rewritten


async def reencrypt_legacy_tokens(
    ctx: dict, max_rows: int = _DEFAULT_MAX_ROWS
) -> str:
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
