"""The fake outside world: Composio (and the apps behind it), Cloudinary, S3 and Resend, in one process.

  python -m briefsim.world.server --port 8711 --out <run dir> --origin <ISO> --days 14

Runs on the simulator's clock, so "now" for every app is the simulated instant. Every call
is appended to <run dir>/world_calls.jsonl with what was answered; a route or slug the fake
does not implement answers 501 and is logged as a sim gap, never answered silently.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import secrets
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
import uvicorn

from briefsim.world.apps import calendar, github, todoist
from briefsim.world.model import App, FaultMode, World
from briefsim.world.scenario import founder_world

SCHEMAS = Path(__file__).resolve().parent / "schemas"
JsonObject = dict[str, object]
_TOOL_APPS = {"GITHUB": App.GITHUB, "TODOIST": App.TODOIST}
_HANDLERS = {**github.HANDLERS, **todoist.HANDLERS}
_PROVIDER_ERRORS: dict[FaultMode, tuple[int, str]] = {
    FaultMode.UNAVAILABLE: (503, "Service Unavailable"),
    FaultMode.DEAD_GRANT: (401, "Bad credentials"),
    FaultMode.RATE_LIMITED: (429, "Too Many Requests"),
}
_RETRY_AFTER_S = "3600"
#: The S3-compatible blob store's path under the world's URL (path-style: /s3/<bucket>/<key>).
S3_PREFIX = "/s3"
_S3_NO_SUCH_KEY = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message></Error>"
)


@dataclass(frozen=True)
class Account:
    persona: str
    app: App


class WorldServer:
    def __init__(self, out: Path, origin: datetime, days: int) -> None:
        self.out = out
        self.origin = origin
        self.days = days
        self.worlds: dict[str, World] = {}
        self.accounts: dict[str, Account] = {}
        #: The vendored Composio tool definitions by slug, and each one's toolkit slug.
        self.tools: dict[str, JsonObject] = {}
        self.toolkit_of: dict[str, str] = {}
        for path in sorted(SCHEMAS.glob("*.json")):
            for tool in json.loads(path.read_text()):
                self.tools[tool["slug"]] = tool
                self.toolkit_of[tool["slug"]] = str(tool["toolkit"]["slug"]).upper()
        (out / "editions").mkdir(parents=True, exist_ok=True)
        (out / "blobs").mkdir(parents=True, exist_ok=True)

    def log(self, **row: object) -> None:
        row = {"at": datetime.now(UTC).isoformat(), **row}
        with (self.out / "world_calls.jsonl").open("a") as sink:
            sink.write(json.dumps(row, default=str) + "\n")

    def register(self, persona: str, accounts: dict[str, str]) -> None:
        self.worlds[persona] = founder_world(self.origin, self.days)
        for app, account_id in accounts.items():
            self.accounts[account_id] = Account(persona, App(app))


def _gap(server: WorldServer, request: Request, why: str) -> JSONResponse:
    server.log(kind="sim_gap", method=request.method, path=request.url.path, why=why)
    return JSONResponse({"error": {"message": f"brief-sim: {why}"}}, status_code=501)


def _composio_routes(server: WorldServer) -> APIRouter:
    """Composio's v3.1 API: the tool catalog, tool execution, the provider proxy, connected accounts."""
    router = APIRouter()

    @router.get("/api/v3.1/tools")
    async def list_tools(request: Request) -> JsonObject:
        query = request.query_params
        toolkit = (query.get("toolkit_slug") or "").upper()
        wanted = {s for s in (query.get("tool_slugs") or "").split(",") if s}
        items = [
            t
            for slug, t in server.tools.items()
            if (not toolkit or server.toolkit_of[slug] == toolkit)
            and (not wanted or slug in wanted)
        ]
        return {
            "items": items,
            "next_cursor": None,
            "total_items": len(items),
            "total_pages": 1,
            "current_page": 1,
        }

    @router.get("/api/v3.1/tools/{slug}")
    async def get_tool(slug: str, request: Request) -> JSONResponse:
        if slug in server.tools:
            return JSONResponse(server.tools[slug])
        return _gap(server, request, f"tool {slug} is not simulated")

    @router.post("/api/v3.1/tools/execute/proxy")
    async def proxy(request: Request) -> JSONResponse:
        body = await request.json()
        account = server.accounts.get(str(body.get("connected_account_id")))
        endpoint = str(body.get("endpoint", ""))
        if account is None or account.app is not App.CALENDAR:
            return _gap(server, request, f"proxy for {endpoint} on an unknown account")
        world = server.worlds[account.persona]
        now = datetime.now(UTC)
        query = {
            p["name"]: p["value"] for p in body.get("parameters") or [] if p.get("type") == "query"
        }
        fault = world.fault_at(App.CALENDAR, now)
        if fault is not None:
            status, reason = _PROVIDER_ERRORS[fault.mode]
            server.log(
                kind="read",
                persona=account.persona,
                app=App.CALENDAR,
                call=endpoint,
                args=query,
                outcome=fault.mode,
            )
            headers = (
                {"retry-after": _RETRY_AFTER_S} if fault.mode is FaultMode.RATE_LIMITED else {}
            )
            google_error = {
                "code": status,
                "message": reason,
                "status": reason.upper().replace(" ", "_"),
            }
            return JSONResponse(
                {"status": status, "data": {"error": google_error}, "headers": headers}
            )
        data: JsonObject
        if endpoint.endswith("/users/me/calendarList"):
            data = calendar.calendar_list(world.timezone)
        elif calendar.calendar_id_of(endpoint) == calendar.CALENDAR_ID:
            data = calendar.events(world.state_at(now), query, world.timezone)
        else:
            return _gap(server, request, f"calendar endpoint {endpoint} is not simulated")
        items = data.get("items")
        server.log(
            kind="read",
            persona=account.persona,
            app=App.CALENDAR,
            call=endpoint,
            args=query,
            outcome="ok",
            items=len(items) if isinstance(items, list) else None,
        )
        return JSONResponse(
            {"status": 200, "data": data, "headers": {"content-type": "application/json"}}
        )

    @router.post("/api/v3.1/tools/execute/{slug}")
    async def execute(slug: str, request: Request) -> JSONResponse:
        body = await request.json()
        account = server.accounts.get(str(body.get("connected_account_id")))
        handler = _HANDLERS.get(slug)
        if account is None or handler is None:
            return _gap(server, request, f"execute {slug} (account known: {account is not None})")
        world = server.worlds[account.persona]
        now = datetime.now(UTC)
        args: JsonObject = body.get("arguments") or {}
        fault = world.fault_at(account.app, now)
        if fault is not None:
            status, reason = _PROVIDER_ERRORS[fault.mode]
            server.log(
                kind="read",
                persona=account.persona,
                app=account.app,
                call=slug,
                args=args,
                outcome=fault.mode,
            )
            error = f"Request failed with status code {status}: {reason}"
            return JSONResponse(
                {
                    "data": {"message": reason, "status": str(status)},
                    "successful": False,
                    "error": error,
                    "log_id": f"log_{secrets.token_hex(6)}",
                }
            )
        data = handler(
            world.state_at(now), args, world.me if account.app is App.GITHUB else world.timezone
        )
        server.log(
            kind="read",
            persona=account.persona,
            app=account.app,
            call=slug,
            args=args,
            outcome="ok",
            items=next((len(v) for v in data.values() if isinstance(v, list)), None),
        )
        return JSONResponse(
            {
                "data": data,
                "successful": True,
                "error": None,
                "log_id": f"log_{secrets.token_hex(6)}",
            }
        )

    @router.get("/api/v3.1/connected_accounts")
    async def list_accounts(request: Request) -> JsonObject:
        toolkits = {
            t.upper()
            for t in request.query_params.getlist("toolkit_slugs")
            for t in t.split(",")
            if t
        }
        items = [
            {
                "id": account_id,
                "status": "ACTIVE",
                "is_disabled": False,
                "user_id": account.persona,
                "toolkit": {"slug": account.app.value},
                "auth_config": {"id": f"ac_{account.app.value}", "is_composio_managed": True},
                "created_at": server.origin.isoformat(),
                "updated_at": server.origin.isoformat(),
            }
            for account_id, account in server.accounts.items()
            if not toolkits or account.app.value.upper() in toolkits
        ]
        return {
            "items": items,
            "next_cursor": None,
            "total_items": len(items),
            "total_pages": 1,
            "current_page": 1,
        }

    return router


def _s3_object(server: WorldServer, bucket: str, key: str) -> Path:
    """Return where an object lives under <run dir>/blobs, one file per bucket/key."""
    return server.out / "blobs" / bucket / key.replace("/", "__")


def _sink_routes(server: WorldServer) -> APIRouter:
    """Where GAIA's output lands: Cloudinary and S3 for files and edition images, Resend for email."""
    router = APIRouter()

    @router.put(S3_PREFIX + "/{bucket}/{key:path}")
    async def s3_put(bucket: str, key: str, request: Request) -> Response:
        content = await request.body()
        _s3_object(server, bucket, key).parent.mkdir(parents=True, exist_ok=True)
        _s3_object(server, bucket, key).write_bytes(content)
        server.log(kind="sink", sink="s3", key=key, bytes=len(content))
        return Response(status_code=200, headers={"ETag": f'"{secrets.token_hex(16)}"'})

    @router.api_route(S3_PREFIX + "/{bucket}/{key:path}", methods=["GET", "HEAD"])
    async def s3_get(bucket: str, key: str) -> Response:
        path = _s3_object(server, bucket, key)
        if not path.exists():
            return Response(_S3_NO_SUCH_KEY, status_code=404, media_type="application/xml")
        return Response(path.read_bytes(), media_type="application/octet-stream")

    @router.delete(S3_PREFIX + "/{bucket}/{key:path}")
    async def s3_delete(bucket: str, key: str) -> Response:
        _s3_object(server, bucket, key).unlink(missing_ok=True)
        server.log(kind="sink", sink="s3_delete", key=key)
        return Response(status_code=204)

    @router.post("/v1_1/{cloud}/image/upload")
    async def cloudinary_upload(
        cloud: str, file: UploadFile, public_id: Annotated[str, Form()]
    ) -> JsonObject:
        content = await file.read()
        path = server.out / "editions" / f"{public_id.replace('/', '_')}.png"
        path.write_bytes(content)
        server.log(kind="sink", sink="cloudinary", public_id=public_id, bytes=len(content))
        url = f"https://res.cloudinary.com/{cloud}/image/upload/v1/{public_id}.png"
        return {
            "public_id": public_id,
            "version": 1,
            "format": "png",
            "resource_type": "image",
            "type": "upload",
            "bytes": len(content),
            "url": url,
            "secure_url": url,
            "created_at": datetime.now(UTC).isoformat(),
        }

    @router.post("/emails")
    async def resend_email(request: Request) -> JsonObject:
        email = await request.json()
        email_id = f"sim-{secrets.token_hex(8)}"
        server.log(
            kind="sink",
            sink="email",
            id=email_id,
            to=email.get("to"),
            subject=email.get("subject"),
            html=email.get("html"),
        )
        return {"id": email_id}

    return router


def build_app(server: WorldServer) -> FastAPI:
    api = FastAPI()
    api.include_router(_composio_routes(server))
    api.include_router(_sink_routes(server))

    @api.post("/_sim/personas/{persona}")
    async def register(persona: str, accounts: dict[str, str]) -> JsonObject:
        server.register(persona, accounts)
        return {"persona": persona, "accounts": len(accounts)}

    @api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def unknown(path: str, request: Request) -> JSONResponse:
        return _gap(server, request, f"route /{path} is not simulated")

    return api


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--origin", type=datetime.fromisoformat, required=True)
    parser.add_argument("--days", type=int, required=True)
    args = parser.parse_args()
    server = WorldServer(args.out, args.origin, args.days)
    uvicorn.run(build_app(server), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
