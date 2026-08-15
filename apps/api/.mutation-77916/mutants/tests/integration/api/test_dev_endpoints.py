"""Integration tests for the dev-only identity + seeding layer.

Covers three surfaces:
- the ``/api/v1/dev`` router (mounted only when the bypass is configured),
- ``dev_service`` seeding/mint logic against mocked real services,
- the ``X-Dev-User`` per-request impersonation in the real WorkOSAuthMiddleware.
"""

from contextlib import asynccontextmanager, contextmanager
import io
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

from bson import ObjectId
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import pytest

from app.constants.auth import DEV_USER_MISSING_HINT
from app.models.user_models import UserDocument
from app.schemas.dev_schemas import DevAgentRunResponse, SeedDevDataResponse

DEV_EMAIL = "dev@gaia.local"


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    yield


def _cors_only(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _build_app() -> FastAPI:
    """Create the real app with a no-op lifespan and CORS-only middleware."""
    with (
        patch("app.core.app_factory.lifespan", _noop_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only),
    ):
        from app.core.app_factory import create_app

        return create_app()


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_XLSX_PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    ),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Inventory" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    ),
    "xl/worksheets/sheet1.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Title</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Year</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Time-Parking 2</t></is></c>'
        '<c r="B2"><v>2009</v></c></row>'
        '<row r="3"><c r="A3" t="inlineStr"><is><t>The Widest Goalpost</t></is></c>'
        '<c r="B3"><v>2021</v></c></row>'
        "</sheetData></worksheet>"
    ),
}


def _minimal_xlsx() -> bytes:
    """A genuine OOXML spreadsheet, built inline (this repo ships no xlsx writer).

    Real bytes matter: the point of the attachment tests is that anydoc actually
    parses them, so a fake payload would defeat the test.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in _XLSX_PARTS.items():
            archive.writestr(name, body)
    return buffer.getvalue()


@contextmanager
def _ingestion_edges_stubbed(capture_metadata=None):
    """Stub only the external edges of FileService.upload.

    Validation, MIME/magic-byte checks, and the local anydoc extraction all run
    for real — those are the behaviour under test. Cloudinary, Mongo, ChromaDB,
    the JuiceFS mirror, and the summarization LLM are the process boundaries a
    CI run cannot reach.
    """
    user = UserDocument.model_validate({"id": str(ObjectId()), "email": DEV_EMAIL, "name": "dev"})

    async def summarize(inputs, config=None):
        del config
        return [SimpleNamespace(text="stub summary") for _ in inputs]

    llm = MagicMock()
    llm.abatch = AsyncMock(side_effect=summarize)

    with (
        patch(
            "app.services.dev_service.require_dev_user",
            new_callable=AsyncMock,
            return_value=user,
        ),
        patch(
            "app.services.files.service.upload_to_cloudinary",
            new_callable=AsyncMock,
            return_value="https://cdn.test/file",
        ),
        patch(
            "app.services.files.service.insert_metadata",
            new_callable=AsyncMock,
            side_effect=capture_metadata,
        ),
        patch("app.services.files.service.index_file", new_callable=AsyncMock),
        patch(
            "app.services.files.service.mirror_upload",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.services.files.service.write_summary_sidecar", new_callable=AsyncMock),
        patch("app.utils.file_utils.get_helper_llm", MagicMock()),
        patch("app.utils.file_utils.with_llm_retry", MagicMock(return_value=llm)),
    ):
        yield


# ---------------------------------------------------------------------------
# Router mounting
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDevRouterMounting:
    async def test_dev_routes_absent_without_bypass(self, monkeypatch):
        """With no DEV_AUTH_BYPASS_EMAIL, the router is never mounted → 404.

        Explicitly clears the bypass rather than relying on the developer's
        ambient .env, which legitimately sets it in local dev.
        """
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", None)
        app = _build_app()

        client = await _client(app)
        async with client:
            response = await client.post("/api/v1/dev/users", json={"email": DEV_EMAIL})
        assert response.status_code == 404

    async def test_dev_routes_mounted_with_bypass(self, monkeypatch):
        """Setting the bypass mounts the router → mint route responds (200)."""
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", DEV_EMAIL)
        app = _build_app()

        with patch(
            "app.api.v1.endpoints.dev.mint_dev_user",
            new_callable=AsyncMock,
            return_value=UserDocument.model_validate(
                {"id": "u1", "email": DEV_EMAIL, "name": "dev"}
            ),
        ) as mock_mint:
            client = await _client(app)
            async with client:
                response = await client.post("/api/v1/dev/users", json={"email": DEV_EMAIL})

        assert response.status_code == 200
        assert response.json()["email"] == DEV_EMAIL
        mock_mint.assert_awaited_once_with(DEV_EMAIL, None)

    # The direct agent-invocation routes run the executor / a subagent with the
    # full tool registry as any impersonated user — the highest-blast-radius
    # surface on the router. Nothing but the mount condition keeps them off a
    # prod deployment, so pin every one of them to 404-when-unmounted. A future
    # refactor that registers any of these on a router assembled outside the
    # ENV+bypass gate (e.g. a stray include_router at import time) fails here
    # instead of silently exposing account-takeover-grade endpoints.
    HIGH_BLAST_RADIUS_ROUTES: ClassVar[list[tuple[str, str, dict[str, str] | None]]] = [
        ("POST", "/api/v1/dev/executor", {"email": DEV_EMAIL, "task": "noop"}),
        ("POST", "/api/v1/dev/subagents/some_agent", {"email": DEV_EMAIL, "task": "noop"}),
        ("POST", "/api/v1/dev/attachments", None),
        ("GET", "/api/v1/dev/subagents", None),
        ("DELETE", "/api/v1/dev/users/dev@gaia.local", None),
    ]

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        HIGH_BLAST_RADIUS_ROUTES,
        ids=lambda v: v if isinstance(v, str) else "",
    )
    async def test_privileged_routes_absent_without_bypass(self, monkeypatch, method, path, body):
        """Every privileged dev route — not just /users — 404s when unmounted."""
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", None)
        app = _build_app()

        client = await _client(app)
        async with client:
            response = await client.request(method, path, json=body)
        assert response.status_code == 404

    async def test_privileged_routes_mounted_with_bypass(self, monkeypatch):
        """With the bypass set, the executor + subagent routes are registered and
        reach their service layer (200) — proving the 404s above are the mount
        gate, not a typo'd path that would 404 in every environment."""
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", DEV_EMAIL)
        app = _build_app()

        agent_result = DevAgentRunResponse(
            user_id="u1",
            conversation_id="c1",
            thread_id="t1",
            agent="executor",
            message="ok",
        )
        with (
            patch(
                "app.api.v1.endpoints.dev.run_executor_direct",
                new_callable=AsyncMock,
                return_value=agent_result,
            ) as mock_exec,
            patch(
                "app.api.v1.endpoints.dev.run_subagent_direct",
                new_callable=AsyncMock,
                return_value=agent_result.model_copy(update={"agent": "some_agent"}),
            ) as mock_sub,
        ):
            client = await _client(app)
            async with client:
                exec_response = await client.post(
                    "/api/v1/dev/executor", json={"email": DEV_EMAIL, "task": "noop"}
                )
                sub_response = await client.post(
                    "/api/v1/dev/subagents/some_agent",
                    json={"email": DEV_EMAIL, "task": "noop"},
                )

        assert exec_response.status_code == 200
        assert sub_response.status_code == 200
        mock_exec.assert_awaited_once_with(DEV_EMAIL, "noop", None)
        mock_sub.assert_awaited_once_with(DEV_EMAIL, "some_agent", "noop", None)

    async def test_seed_endpoint_forwards_payload(self, monkeypatch):
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", DEV_EMAIL)
        app = _build_app()

        with patch(
            "app.api.v1.endpoints.dev.seed_dev_data",
            new_callable=AsyncMock,
            return_value=SeedDevDataResponse(
                email=DEV_EMAIL,
                user_id="u1",
                todos_created=3,
                conversations_created=2,
                platforms_linked=["telegram"],
                platform_user_ids={"telegram": "dev-telegram-u1"},
            ),
        ) as mock_seed:
            client = await _client(app)
            async with client:
                response = await client.post(
                    "/api/v1/dev/seed",
                    json={
                        "email": DEV_EMAIL,
                        "todos": 3,
                        "conversations": 2,
                        "platform_links": ["telegram"],
                    },
                )

        assert response.status_code == 200
        body = response.json()
        assert body["todos_created"] == 3
        assert body["conversations_created"] == 2
        mock_seed.assert_awaited_once_with(DEV_EMAIL, 3, 2, ["telegram"])


# ---------------------------------------------------------------------------
# Service logic
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDevServiceLogic:
    async def test_mint_is_idempotent(self):
        """Repeated mints return the same user id (find-or-create delegated)."""
        from app.services import dev_service

        oid = ObjectId()
        user = dev_service.UserDocument.model_validate(
            {"id": str(oid), "email": DEV_EMAIL, "name": "dev"}
        )

        with (
            patch.object(
                dev_service,
                "store_user_info",
                new_callable=AsyncMock,
                side_effect=[(oid, True), (oid, False)],
            ),
            patch.object(
                dev_service.user_repository, "get", new_callable=AsyncMock, return_value=user
            ),
        ):
            first = await dev_service.mint_dev_user(DEV_EMAIL)
            second = await dev_service.mint_dev_user(DEV_EMAIL)

        assert first.id == second.id == str(oid)
        assert first.email == DEV_EMAIL

    async def test_seed_creates_expected_counts(self):
        """Seed calls the real create paths exactly N times each."""
        from app.services import dev_service

        oid = ObjectId()
        user = dev_service.UserDocument.model_validate({"id": str(oid), "email": DEV_EMAIL})
        mock_complete = AsyncMock()
        with (
            patch.object(
                dev_service.user_repository,
                "get_by_email",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch.object(dev_service.user_repository, "complete_onboarding", mock_complete),
            patch.object(dev_service, "create_todo", new_callable=AsyncMock) as mock_todo,
            patch.object(
                dev_service, "create_conversation_service", new_callable=AsyncMock
            ) as mock_convo,
            patch.object(
                dev_service.PlatformLinkService, "link_account", new_callable=AsyncMock
            ) as mock_link,
        ):
            result = await dev_service.seed_dev_data(
                DEV_EMAIL, todos=3, conversations=2, platform_links=["telegram", "slack"]
            )

        assert mock_todo.await_count == 3
        assert mock_convo.await_count == 2
        assert mock_link.await_count == 2
        assert result.todos_created == 3
        assert result.conversations_created == 2
        assert result.platforms_linked == ["telegram", "slack"]
        assert result.user_id == str(oid)

        # Seeding marks onboarding complete via the gated repository method.
        assert mock_complete.await_args.args[0] == str(oid)
        assert mock_complete.await_args.kwargs["phase"] == dev_service.OnboardingPhase.COMPLETED

    async def test_seed_rejects_unknown_platform_before_writing(self):
        """An invalid platform aborts with 400 and writes nothing."""
        from app.services import dev_service
        from app.utils.errors import AppError

        user = dev_service.UserDocument.model_validate({"id": str(ObjectId()), "email": DEV_EMAIL})
        with (
            patch.object(
                dev_service.user_repository,
                "get_by_email",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch.object(dev_service, "create_todo", new_callable=AsyncMock) as mock_todo,
        ):
            with pytest.raises(AppError) as exc:
                await dev_service.seed_dev_data(
                    DEV_EMAIL, todos=1, conversations=0, platform_links=["myspace"]
                )

        assert exc.value.status_code == 400
        mock_todo.assert_not_awaited()

    async def test_seed_missing_user_404_with_hint(self):
        from app.services import dev_service
        from app.utils.errors import AppError

        with patch.object(
            dev_service.user_repository, "get_by_email", new_callable=AsyncMock, return_value=None
        ):
            with pytest.raises(AppError) as exc:
                await dev_service.seed_dev_data(
                    DEV_EMAIL, todos=1, conversations=0, platform_links=[]
                )

        assert exc.value.status_code == 404
        assert DEV_USER_MISSING_HINT in exc.value.fix


# ---------------------------------------------------------------------------
# X-Dev-User impersonation (real WorkOSAuthMiddleware)
# ---------------------------------------------------------------------------


def _build_bypass_probe_app() -> FastAPI:
    """A minimal app running the real bypass middleware plus a probe route."""
    from app.api.v1.middleware.auth import WorkOSAuthMiddleware

    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request) -> JSONResponse:
        user = getattr(request.state, "user", None)
        if not user:
            return JSONResponse(status_code=401, content={"detail": "no user"})
        return JSONResponse(
            content={"email": user.get("email"), "dev_bypass": user.get("dev_bypass")}
        )

    app.add_middleware(WorkOSAuthMiddleware, workos_client=MagicMock())
    return app


@pytest.mark.integration
class TestDevUserImpersonation:
    @pytest.fixture
    def bypass_users(self):
        return {
            email: UserDocument.model_validate(
                {"id": str(ObjectId()), "email": email, "name": name}
            )
            for email, name in ((DEV_EMAIL, "Dev"), ("other@gaia.local", "Other"))
        }

    @pytest.fixture
    async def probe_client(self, monkeypatch, bypass_users):
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", DEV_EMAIL)

        async def fake_get_by_email(email):
            return bypass_users.get(email)

        with patch(
            "app.api.v1.middleware.auth.user_repository.get_by_email",
            AsyncMock(side_effect=fake_get_by_email),
        ):
            app = _build_bypass_probe_app()
            client = await _client(app)
            async with client:
                yield client

    async def test_defaults_to_env_email(self, probe_client):
        response = await probe_client.get("/probe")
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == DEV_EMAIL
        assert body["dev_bypass"] is True

    async def test_header_switches_user(self, probe_client):
        response = await probe_client.get("/probe", headers={"X-Dev-User": "other@gaia.local"})
        assert response.status_code == 200
        assert response.json()["email"] == "other@gaia.local"

    async def test_unknown_header_email_401_with_hint(self, probe_client):
        response = await probe_client.get("/probe", headers={"X-Dev-User": "ghost@nope.local"})
        assert response.status_code == 401
        assert DEV_USER_MISSING_HINT in response.text


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDevAttachments:
    """The dev attachment route must run the product's ingestion, not a copy of it.

    The GAIA-Bench harness skipped 34 of 165 rows on the belief that attachments
    were a product gap; they were not — only this endpoint was missing. A dev
    route that re-implemented extraction would make the benchmark green while
    testing code no user runs, so these tests let the REAL anydoc extraction run
    and assert on cell text only a real .xlsx parse can produce. Only the
    genuinely external edges (Cloudinary, Mongo, ChromaDB, the summary LLM, the
    JuiceFS mirror) are stubbed.
    """

    @pytest.fixture
    def app(self, monkeypatch):
        from app.config.settings import settings as app_settings

        monkeypatch.setattr(app_settings, "DEV_AUTH_BYPASS_EMAIL", DEV_EMAIL)
        return _build_app()

    async def test_upload_extracts_real_spreadsheet_content(self, app):
        """A real .xlsx POSTed to the route comes back with its actual cells."""
        stored: dict[str, object] = {}

        async def capture_metadata(document):
            stored["document"] = document

        with _ingestion_edges_stubbed(capture_metadata):
            client = await _client(app)
            async with client:
                response = await client.post(
                    "/api/v1/dev/attachments",
                    data={"email": DEV_EMAIL, "conversation_id": "conv-xlsx-1"},
                    files={"file": ("inventory.xlsx", _minimal_xlsx(), XLSX_MIME)},
                )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["type"] == XLSX_MIME
        assert body["conversation_id"] == "conv-xlsx-1"

        pages = body["page_wise_summary"]
        assert isinstance(pages, list) and pages, body
        content = pages[0]["data"]["content"]
        # Cell values that exist only inside the .xlsx bytes — a stubbed or
        # re-implemented extractor cannot produce them.
        assert "Time-Parking 2" in content
        assert "The Widest Goalpost" in content
        assert "2009" in content

        # Persisted with the conversation id, which is what makes the file
        # reachable from a later /dev/executor run on the same conversation.
        assert stored["document"].conversation_id == "conv-xlsx-1"

    async def test_upload_rejects_a_content_type_the_product_rejects(self, app):
        """The dev route inherits the shipped allowlist — it does not widen it."""
        with _ingestion_edges_stubbed():
            client = await _client(app)
            async with client:
                response = await client.post(
                    "/api/v1/dev/attachments",
                    data={"email": DEV_EMAIL, "conversation_id": "conv-zip-1"},
                    files={"file": ("archive.zip", b"PK\x03\x04zip", "application/zip")},
                )

        assert response.status_code == 415, response.text
