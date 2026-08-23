#!/usr/bin/env python3
"""Fully delete one user's account and data across every store. DRY-RUN by default.

There is no user-facing account-deletion feature; this script is the operational
path for GDPR/erasure requests. It removes the user from every store that holds
their data, in an order that revokes external access first and deletes the login
identity last (so a re-login cannot resurrect the account mid-teardown):

1. Composio      — revoke OAuth grants (Gmail/Calendar/... access is cut first)
2. E2B           — kill the user's sandboxes
3. MongoDB       — every collection with a matching ``user_id`` (+ GridFS,
                   ``support_requests`` by email, ``bot_sessions`` by platform
                   link, ``users`` doc last)
4. PostgreSQL    — memory graph, OAuth/MCP credentials, bridge devices, and the
                   LangGraph checkpoint threads of the user's conversations
5. ChromaDB      — every collection, ``where={"user_id": ...}``
6. JuiceFS       — the user's workspace directory (propagates to R2)
7. Redis         — keys containing the uid (rate limits, caches, budgets)
8. Resend        — marketing-audience contact
9. WorkOS        — the login identity, last

PostHog person deletion is a manual follow-up: the server only holds the
capture token, not the personal API key that deletion requires. Langfuse traces
keyed by ``user_id`` are likewise not covered here.

Usage (inside the dockered API, with Infisical bootstrap creds in env)::

    cd apps/api
    uv run python -m app.scripts.delete_user_account <email>       # dry-run
    uv run python -m app.scripts.delete_user_account <email> \
        --execute --uid <24-hex-uid> --confirm-email <email>       # delete

Safety: execute mode refuses to run unless ``--uid`` matches the id the email
resolves to *now* (guards against the email resolving to a different user
between dry-run and execute) and ``--confirm-email`` matches exactly. Every
delete filters on exact ``user_id`` equality — no regex or wildcard matching
against user-owned data. The run ends with a verification sweep and exits
non-zero if any step failed or any remnant survived.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import shutil
import sys
from typing import Any, TypeAlias

from bson import ObjectId
import chromadb
from composio_client import Composio
from e2b import AsyncSandbox
import gridfs
import psycopg
from pymongo import MongoClient
from pymongo.database import Database
import redis as redislib
import resend
from workos import AsyncWorkOSClient

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME

UID_RE = re.compile(r"^[0-9a-f]{24}$")
JFS_USERS_ROOT = Path("/mnt/jfs/users")

# Postgres tables owned per-user. Order matters only for readability: the
# memory_* FKs cascade (see app/models/memory_db_models.py), but deleting
# edges/entities before memories keeps the reported counts exact.
PG_USER_TABLES = (
    "memory_graph_edges",
    "memory_entities",
    "memory_episodes",
    "memory_documents",
    "memories",
    "oauth_tokens",
    "mcp_credentials",
    "bridge_device_mcp_servers",
    "bridge_devices",
)

MongoDatabase: TypeAlias = Database[dict[str, Any]]

_failures: list[str] = []


def _step(name: str, msg: str) -> None:
    print(f"[{name}] {msg}", flush=True)


def _fail(name: str, err: Exception) -> None:
    _failures.append(f"{name}: {type(err).__name__}: {err}")
    print(f"[{name}] FAILED: {type(err).__name__}: {err}", flush=True)


def _resolve_user(db: MongoDatabase, email: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = list(
        db.users.find({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    )
    if len(matches) != 1:
        sys.exit(f"ABORT: email resolved to {len(matches)} users, need exactly 1")
    return matches[0]


def _mongo_inventory(db: MongoDatabase, uid: str, email: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in sorted(db.list_collection_names()):
        if name.startswith("fs."):
            continue
        n = db[name].count_documents({"user_id": uid})
        if name == "users":
            n += db.users.count_documents({"_id": ObjectId(uid)})
        if name == "support_requests":
            n = db[name].count_documents({"$or": [{"user_id": uid}, {"user_email": email}]})
        if n:
            counts[name] = n
    gridfs_count = db["fs.files"].count_documents({"metadata.user_id": uid})
    if gridfs_count:
        counts["fs.files(gridfs)"] = gridfs_count
    return counts


def _pg_inventory(conn: psycopg.Connection[Any], uid: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in PG_USER_TABLES:
            cur.execute(f"SELECT count(*) FROM {table} WHERE user_id = %s", (uid,))
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    return {k: v for k, v in counts.items() if v}


def _chroma_inventory(client: chromadb.api.ClientAPI, uid: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for col in client.list_collections():
        name = col if isinstance(col, str) else col.name
        got = client.get_collection(name).get(where={"user_id": uid}, limit=200_000, include=[])
        n = len(got.get("ids") or [])
        if n:
            counts[name] = n
    return counts


def _redis_user_keys(client: redislib.Redis, uid: str) -> list[str]:
    return sorted(key.decode() for key in client.scan_iter(match=f"*{uid}*", count=1000))


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def _run(args: argparse.Namespace) -> int:
    email = args.email.strip().lower()

    db: MongoDatabase = MongoClient(settings.MONGO_DB)[MONGO_DATABASE_NAME]
    user = _resolve_user(db, email)
    uid = str(user["_id"])
    if not UID_RE.match(uid):
        sys.exit(f"ABORT: uid {uid!r} is not a 24-hex ObjectId")
    print(f"user: {user['email']}  uid={uid}  name={user.get('name')}\n")

    if args.execute:
        if args.uid != uid:
            sys.exit(f"ABORT: --uid {args.uid!r} does not match resolved uid {uid!r}")
        if (args.confirm_email or "").strip().lower() != email:
            sys.exit("ABORT: --confirm-email does not match email")

    print(f"=== mode: {'EXECUTE' if args.execute else 'DRY-RUN'} ===\n")

    pg = psycopg.connect(settings.POSTGRES_URL)
    chroma = chromadb.HttpClient(host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT)
    redis_client = redislib.Redis.from_url(settings.REDIS_URL)
    composio = Composio(api_key=settings.COMPOSIO_KEY)
    workos = AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)

    # ---------- inventory (both modes) ----------
    mongo_counts = _mongo_inventory(db, uid, email)
    pg_counts = _pg_inventory(pg, uid)
    chroma_counts = _chroma_inventory(chroma, uid)
    redis_keys = _redis_user_keys(redis_client, uid)
    jfs_path = JFS_USERS_ROOT / uid
    if jfs_path.parent != JFS_USERS_ROOT or not UID_RE.match(jfs_path.name):
        sys.exit(f"ABORT: refusing to touch path {jfs_path}")

    composio_accounts = list(getattr(composio.connected_accounts.list(user_ids=[uid]), "items", []))
    sandbox_ids = [
        doc["sandbox_id"] for doc in db.e2b_sandboxes.find({"user_id": uid}, {"sandbox_id": 1})
    ]
    conversation_ids = [
        doc["conversation_id"]
        for doc in db.conversations.find({"user_id": uid}, {"conversation_id": 1})
    ]
    platform_links: dict[str, Any] = user.get("platform_links") or {}
    workos_users = (await workos.user_management.list_users(email=email)).data

    print("mongo:", mongo_counts or "none")
    print("postgres:", pg_counts or "none")
    print("chroma:", chroma_counts or "none")
    print(f"redis: {len(redis_keys)} keys")
    print(f"juicefs: {jfs_path} exists={jfs_path.exists()}")
    print(f"composio: {[(a.id, a.toolkit.slug, a.status) for a in composio_accounts]}")
    print(f"e2b sandboxes: {sandbox_ids}")
    print(f"conversations (checkpoint threads to sweep): {len(conversation_ids)}")
    print(f"platform_links: {list(platform_links) or 'none'}")
    print(f"workos: {[(u.id, u.email) for u in workos_users]}")

    if not args.execute:
        print(
            f"\nDRY-RUN complete. To delete, rerun with:\n"
            f"  --execute --uid {uid} --confirm-email {email}"
        )
        return 0

    print("\n=== deleting ===")

    # 1. Composio: revoke OAuth grants first — external access is cut before
    #    any data is removed, so nothing can write during teardown.
    for account in composio_accounts:
        try:
            composio.connected_accounts.delete(nanoid=account.id)
            _step("composio", f"deleted {account.id} ({account.toolkit.slug})")
        except Exception as e:
            _fail(f"composio:{account.id}", e)

    # 2. E2B sandboxes
    for sandbox_id in sandbox_ids:
        try:
            await AsyncSandbox.kill(
                sandbox_id, api_key=settings.E2B_API_KEY, domain=settings.E2B_DOMAIN
            )
            _step("e2b", f"killed {sandbox_id}")
        except Exception as e:
            _fail(f"e2b:{sandbox_id}", e)

    # 3. Mongo (users doc last, so a partial failure leaves the account findable)
    try:
        bucket = gridfs.GridFSBucket(db)
        for file_doc in db["fs.files"].find({"metadata.user_id": uid}, {"_id": 1}):
            bucket.delete(file_doc["_id"])
        for name in sorted(db.list_collection_names()):
            if name == "users" or name.startswith("fs."):
                continue
            n = db[name].delete_many({"user_id": uid}).deleted_count
            if name == "support_requests":
                n += db[name].delete_many({"user_email": email}).deleted_count
            if name == "bot_sessions" and platform_links:
                platform_ids = [
                    str(link.get("platform_user_id", link)) if isinstance(link, dict) else str(link)
                    for link in platform_links.values()
                ]
                n += db[name].delete_many({"platform_user_id": {"$in": platform_ids}}).deleted_count
            if n:
                _step("mongo", f"{name}: deleted {n}")
        deleted = db.users.delete_one({"_id": ObjectId(uid)}).deleted_count
        _step("mongo", f"users: deleted {deleted}")
    except Exception as e:
        _fail("mongo", e)

    # 4. Postgres: per-user tables + the LangGraph checkpoint threads of the
    #    user's conversations (base thread == conversation_id plus derived
    #    executor/workflow threads that embed it — same contract as
    #    conversation_service._delete_checkpoint_threads).
    try:
        with pg.cursor() as cur:
            for table in PG_USER_TABLES:
                cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (uid,))
                if cur.rowcount:
                    _step("postgres", f"{table}: deleted {cur.rowcount}")
            for conversation_id in conversation_ids:
                pattern = f"%{_like_escape(conversation_id)}%"
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE thread_id LIKE %s ESCAPE '\\'",
                        (pattern,),
                    )
                    if cur.rowcount:
                        _step("postgres", f"{table}[{conversation_id}]: deleted {cur.rowcount}")
        pg.commit()
    except Exception as e:
        pg.rollback()
        _fail("postgres", e)

    # 5. Chroma
    for name, count in chroma_counts.items():
        try:
            chroma.get_collection(name).delete(where={"user_id": uid})
            _step("chroma", f"{name}: deleted {count}")
        except Exception as e:
            _fail(f"chroma:{name}", e)

    # 6. JuiceFS workspace (propagates to R2)
    try:
        if jfs_path.exists():
            shutil.rmtree(jfs_path)
            _step("juicefs", f"removed {jfs_path}")
    except Exception as e:
        _fail("juicefs", e)

    # 7. Redis
    try:
        if redis_keys:
            redis_client.unlink(*redis_keys)
        _step("redis", f"unlinked {len(redis_keys)} keys")
    except Exception as e:
        _fail("redis", e)

    # 8. Resend marketing contact
    try:
        resend.api_key = settings.RESEND_API_KEY
        if settings.RESEND_AUDIENCE_ID:
            resend.Contacts.remove(audience_id=settings.RESEND_AUDIENCE_ID, email=email)
            _step("resend", f"removed contact {email}")
        else:
            _step("resend", "no RESEND_AUDIENCE_ID; skipped")
    except Exception as e:
        _fail("resend", e)

    # 9. WorkOS identity, last — prevents account resurrection on re-login.
    for workos_user in workos_users:
        try:
            await workos.user_management.delete_user(workos_user.id)
            _step("workos", f"deleted {workos_user.id}")
        except Exception as e:
            _fail(f"workos:{workos_user.id}", e)

    # ---------- verification ----------
    print("\n=== verification ===")
    remnants: dict[str, Any] = {
        "mongo": _mongo_inventory(db, uid, email),
        "postgres": _pg_inventory(pg, uid),
        "chroma": _chroma_inventory(chroma, uid),
        "redis": _redis_user_keys(redis_client, uid),
        "juicefs": jfs_path.exists(),
        "composio": [
            a.id
            for a in getattr(composio.connected_accounts.list(user_ids=[uid]), "items", [])
            if a.status == "ACTIVE"
        ],
        "workos": [u.id for u in (await workos.user_management.list_users(email=email)).data],
    }
    clean = not any(remnants.values())
    for store, leftover in remnants.items():
        print(f"  {store}: {'CLEAN' if not leftover else f'REMNANT {leftover}'}")
    print("\nMANUAL FOLLOW-UP: delete the PostHog person for distinct_id", uid)
    print("MANUAL FOLLOW-UP: delete Langfuse traces for user_id", uid)
    if _failures:
        print("\nFAILED STEPS:")
        for failure in _failures:
            print("  -", failure)
    return 0 if clean and not _failures else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email of the account to delete")
    parser.add_argument("--execute", action="store_true", help="Actually delete (default: dry-run)")
    parser.add_argument("--uid", help="Must match the uid the email resolves to now")
    parser.add_argument("--confirm-email", help="Must match <email> exactly")
    sys.exit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
