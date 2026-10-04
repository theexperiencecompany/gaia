"""Dagger CI/CD pipeline for the GAIA monorepo.

Provides containerized quality checks and Docker image build/publish
functions that run identically locally and in CI.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Any

import dagger
from dagger import DefaultPath, Doc, Ignore, dag, function, object_type

# Patterns excluded from the source context for all functions.
# Keep this tight -- unnecessary files slow down the filesync to the engine.
# A bare name matches only at the root; per-package build/cache dirs need **/.
_IGNORE = [
    "**/node_modules",
    ".conductor",
    "**/.next",
    "**/__pycache__",
    "**/.venv",
    "**/dist",
    ".nx/cache",
    ".nx/workspace-data",
    ".pnpm-store",
    "chroma-data",
    ".git",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/.coverage",
    "**/coverage",
    ".wwebjs_auth",
    ".wwebjs_cache",
    "**/.hypothesis",
    "**/out",
    ".agents/plans",
]

# Service images pinned by digest (tag kept for readability). Keep in sync
# with scripts/ci/test-services.sh (the CI variant of this topology).
_POSTGRES_IMAGE = "postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
_REDIS_IMAGE = (
    "redis:7.4.9-alpine3.21@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
)
_MONGO_IMAGE = (
    "mongo:7.0.37@sha256:340c1c56fb10e95cf79ff547f8664b96bc6ead9909bc355238cbf865a9695a6f"
)
_CHROMA_IMAGE = (
    "chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6"
)
_RABBITMQ_IMAGE = (
    "rabbitmq:3.13.7-alpine@sha256:d7af1c87c5f1eda13fcfca06db452bf3aeab6619fc3358b68535c0c02c4e52bc"
)

# The one definition of the test-python slices; main.yml's matrix reads it too.
_SLICES_FILE = "scripts/ci/lib/test-slices.json"
# Mounted as a cache volume; the warmup below is the one setup-python-test-env runs.
_MODEL_CACHE_DIR = "/root/.cache/fastembed"
_PREFETCH_MODELS = (
    "from app.memory.embeddings import _embed_sync, _rerank_sync\n"
    "_embed_sync(['warmup'])\n"
    "_rerank_sync('warmup', ['warmup document'])"
)

# Type alias for the annotated source directory used by all functions.
Source = Annotated[
    dagger.Directory,
    DefaultPath("/"),
    Ignore(_IGNORE),
    Doc("Repository source directory"),
]


@object_type
class GaiaCi:
    """CI/CD pipeline for the GAIA monorepo."""

    # ── Environment ──────────────────────────────────────────────

    @function
    def base_image(self) -> dagger.Container:
        """Build the CI base image using SDK-native calls for optimal layer caching.

        Each with_exec() becomes an individually cacheable layer in Dagger's
        content-addressable cache. Unlike docker_build(), these layers are
        eligible for remote caching via Dagger Cloud without any special config.
        """
        return (
            dag.container()
            .from_("node:22.15.1-bookworm-slim")
            .with_exec(
                [
                    "sh",
                    "-c",
                    (
                        "apt-get update"
                        " && apt-get install -y --no-install-recommends"
                        " python3 python3-pip python3-venv python3-dev"
                        " git curl build-essential libpq-dev time"
                        " && apt-get clean"
                        " && rm -rf /var/lib/apt/lists/*"
                    ),
                ]
            )
            .with_exec(
                [
                    "sh",
                    "-c",
                    "corepack enable && corepack prepare pnpm@10.17.1 --activate",
                ]
            )
            .with_exec(["pip", "install", "--break-system-packages", "uv"])
        )

    @function
    def ci_env(self, source: Source) -> dagger.Container:
        """Create a full CI environment with dependency installation.

        Dependency install layers are separated from source copy: lockfiles
        are mounted first so pnpm/uv install layers are cache-stable when
        only application code changes. The full source is mounted afterwards.
        """
        pnpm_cache = dag.cache_volume("pnpm-store")
        uv_cache = dag.cache_volume("uv-cache")
        nx_cache = dag.cache_volume("nx-cache")
        next_cache = dag.cache_volume("next-cache")
        pip_cache = dag.cache_volume("pip-cache")

        base = self.base_image()

        # Step 1: Mount only lockfiles and install dependencies.
        # This layer is invalidated only when lockfiles change, not on every
        # source code change -- a critical optimization for cache hit rate.
        with_deps = (
            base.with_mounted_cache("/root/.local/share/pnpm/store", pnpm_cache)
            .with_mounted_cache("/root/.cache/uv", uv_cache)
            .with_mounted_cache("/root/.cache/pip", pip_cache)
            .with_workdir("/app")
            .with_file("/app/package.json", source.file("package.json"))
            .with_file("/app/pnpm-lock.yaml", source.file("pnpm-lock.yaml"))
            .with_file("/app/pnpm-workspace.yaml", source.file("pnpm-workspace.yaml"))
            .with_file("/app/uv.lock", source.file("uv.lock"))
            .with_file("/app/pyproject.toml", source.file("pyproject.toml"))
            # Mount all workspace config files and the shared lib source.
            # Globs ensure new workspace members are picked up automatically.
            .with_directory(
                "/app",
                source,
                include=[
                    "**/package.json",
                    "**/pyproject.toml",
                    # uv run re-creates a venv built on another interpreter, with
                    # default groups only; sync must see the same pin it will.
                    "**/.python-version",
                    "libs/**",
                    # pnpm.patchedDependencies in the root package.json points here;
                    # --frozen-lockfile reads the patch files during install, so they
                    # must exist in this dependency layer (before the full source mount).
                    "patches/**",
                ],
            )
            .with_exec(["pnpm", "install", "--frozen-lockfile"])
            .with_exec(
                [
                    "uv",
                    "sync",
                    "--frozen",
                    "--package",
                    "gaia",
                    "--group",
                    "backend",
                    "--group",
                    "dev",
                ]
            )
        )

        # Step 2: Layer the full source on top of the cached dependency layer.
        return (
            with_deps.with_mounted_cache("/app/.nx/cache", nx_cache)
            .with_mounted_cache("/app/apps/web/.next/cache", next_cache)
            .with_directory("/app", source)
            .with_workdir("/app")
        )

    # ── Individual checks ────────────────────────────────────────

    @function
    async def lint(self, source: Source) -> str:
        """Run linting across the monorepo (Biome for JS/TS, Ruff for Python)."""
        return await (
            self.ci_env(source)
            .with_exec(["npx", "nx", "run-many", "-t", "lint", "--parallel=3"])
            .stdout()
        )

    @function
    async def type_check(self, source: Source) -> str:
        """Run type checking (TypeScript + mypy)."""
        return await (
            self.ci_env(source)
            .with_workdir("/app/apps/api")
            .with_exec(["uv", "run", "mypy", "app", "--ignore-missing-imports"])
            .with_workdir("/app")
            .with_exec(["npx", "nx", "run-many", "-t", "type-check", "--parallel=3"])
            .stdout()
        )

    @function
    async def build(self, source: Source) -> str:
        """Build all projects."""
        return await (
            self.ci_env(source)
            .with_env_variable("NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com")
            .with_exec(["npx", "nx", "run-many", "-t", "build", "--parallel=3"])
            .stdout()
        )

    @function
    async def test(self, source: Source) -> str:
        """Run all tests with a small local worker budget, Python before TypeScript."""
        results = [
            await self.test_python(source, worker_limit=2),
            await self.test_typescript(source, parallelism=1),
        ]
        labels = ["PYTHON TESTS", "TYPESCRIPT TESTS"]
        sections = []
        for label, output in zip(labels, results):
            sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")
        return "\n\n".join(sections)

    @staticmethod
    def _assert_pytest_passed(output: str) -> None:
        """Fail on a real pytest failure using pytest's own exit code.

        The container appends `GAIA_PYTEST_EXIT=<code>` as the final stdout line.
        We key off that authoritative code rather than grepping a summary line
        that Dagger can truncate from long logs. A missing sentinel means the run
        never finished cleanly (e.g. an xdist worker crash) and is a failure.

        On failure the full pytest output is attached to the error so the failing
        test names and tracebacks surface in the CI log — Dagger otherwise drops a
        raising function's captured stdout, leaving only the bare exit code.
        """
        codes = re.findall(r"GAIA_PYTEST_EXIT=(\d+)", output)
        if not codes:
            raise RuntimeError(
                "pytest did not report an exit code — the run was interrupted "
                f"(worker crash or container error), treating as a failure.\n\n{output}"
            )
        code = int(codes[-1])
        if code != 0:
            raise RuntimeError(f"pytest failed with exit code {code}.\n\n{output}")

    @function
    async def test_python(
        self,
        source: Source,
        slice_name: Annotated[
            str, Doc("A slice in scripts/ci/lib/test-slices.json; empty runs all in turn")
        ] = "",
        worker_limit: Annotated[
            int, Doc("Optional local cap for xdist workers per Python test slice; 0 uses CI settings")
        ] = 0,
    ) -> str:
        """Run the test-python slices exactly as main.yml does: same file, same runner script."""
        slices = json.loads(await source.file(_SLICES_FILE).contents())["slices"]
        chosen = [s for s in slices if not slice_name or s["name"] == slice_name]
        if not chosen:
            names = ", ".join(s["name"] for s in slices)
            raise ValueError(f"unknown slice {slice_name!r}; {_SLICES_FILE} defines: {names}")
        outputs = [await self._run_slice(source, s, worker_limit=worker_limit) for s in chosen]
        return "\n".join(outputs)

    async def _run_slice(
        self, source: Source, spec: dict[str, Any], *, worker_limit: int = 0
    ) -> str:
        """Run one slice through scripts/ci/pytest.sh slice, with services if it needs them."""
        needs_services = spec["services"] == "true"
        container = (
            self._service_test_container(source) if needs_services else self.ci_env(source)
        )
        container = (
            container.with_mounted_cache(_MODEL_CACHE_DIR, dag.cache_volume("fastembed-models"))
            .with_env_variable("ENV", "test")
            .with_env_variable("MODEL_CACHE_DIR", _MODEL_CACHE_DIR)
            .with_env_variable("MEMORY_MODEL_CACHE_DIR", _MODEL_CACHE_DIR)
            .with_workdir("/app/apps/api")
        )
        prelude = ""
        if needs_services:
            # CI prefetches the models once and serves them from one sidecar, so
            # xdist workers do not each load ~1.3 GB of ONNX weights. The sidecar
            # runs in the background, so it must share the pytest exec.
            container = container.with_exec(
                ["uv", "run", "--frozen", "--no-sync", "python", "-c", _PREFETCH_MODELS]
            )
            prelude = (
                "(cd /app && GITHUB_ENV=/tmp/sidecar.env"
                " bash scripts/ci/embedding-sidecar.sh start)"
                " && set -a && . /tmp/sidecar.env && set +a && "
            )
        workers = (
            "0"
            if spec["serial"] == "true"
            else str(min(int(spec["workers"]), worker_limit))
            if worker_limit
            else spec["workers"]
        )
        runs = " && ".join(
            f"bash /app/scripts/ci/pytest.sh {step}" for step in ["slice", *spec["after"]]
        )
        output = await (
            container.with_env_variable("SLICE_NAME", spec["name"])
            .with_env_variable("SLICE_PATHS", spec["paths"])
            .with_env_variable("SLICE_IGNORE", spec["ignore"])
            .with_env_variable("XDIST_N", workers)
            # What a PR lane runs under (main.yml test-python).
            .with_env_variable("HYPOTHESIS_PROFILE", "ci")
            # Emit the runner's real exit code as the final line: the shell exits 0
            # so Dagger returns the full stdout, and _assert_pytest_passed fails on it.
            .with_exec(
                [
                    "bash",
                    "-c",
                    f'{prelude}{runs}; echo "GAIA_PYTEST_EXIT=$?"',
                ]
            )
            .stdout()
        )
        self._assert_pytest_passed(output)
        return output

    @function
    async def test_python_coverage(self, source: Source) -> str:
        """Run all Python tests with live services and coverage reporting."""
        pytest_cmd = (
            "uv run --frozen pytest -n auto -m 'not composio' --tb=short -q "
            "--cov=app --cov-report=term-missing --cov-fail-under=80 "
            "--override-ini=addopts=--strict-markers"
        )
        output = await (
            self._service_test_container(source)
            .with_exec(["sh", "-c", f'{pytest_cmd}; echo "GAIA_PYTEST_EXIT=$?"'])
            .stdout()
        )
        self._assert_pytest_passed(output)
        return output

    @function
    async def test_typescript(
        self, source: Source, projects: str = "", parallelism: int = 3
    ) -> str:
        """Run JS/TS tests via Nx, preserving diagnostics when the suite fails."""
        cmd = ["npx", "nx", "run-many", "-t", "test", f"--parallel={parallelism}"]
        if projects:
            cmd.extend(["-p", projects])
        execution = (
            self.ci_env(source)
            .with_env_variable("ENV", "test")
            .with_exec(cmd, expect=dagger.ReturnType.ANY)
        )
        output = await execution.stdout()
        exit_code = await execution.exit_code()
        if exit_code:
            raise RuntimeError(f"TypeScript tests failed with exit code {exit_code}.\n\n{output}")
        return output

    @function
    async def dead_code(self, source: Source) -> str:
        """Run dead code detection (vulture for Python, knip for TypeScript)."""
        return await (
            self.ci_env(source)
            .with_exec(["uv", "tool", "install", "vulture"])
            .with_env_variable(
                "PATH",
                "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            )
            .with_exec(["bash", "scripts/dead-code-check.sh"])
            .stdout()
        )

    @function
    async def validate_release(self, source: Source) -> str:
        """Validate release manifest versions."""
        return await (
            self.ci_env(source)
            .with_exec(["node", "scripts/ci/release.mjs", "validate-manifest"])
            .stdout()
        )

    # ── Service containers (for integration tests) ───────────────

    @function
    def postgres_service(self) -> dagger.Service:
        """Start a PostgreSQL 16 service container."""
        return (
            dag.container()
            .from_(_POSTGRES_IMAGE)
            .with_env_variable("POSTGRES_USER", "gaia")
            .with_env_variable("POSTGRES_PASSWORD", "gaia")
            .with_env_variable("POSTGRES_DB", "gaia_test")
            .with_exposed_port(5432)
            # Default args, not as_service(args=...): dagger.json pins no engineVersion,
            # so the module runs on the compat API where asService takes no arguments.
            .with_default_args(
                [
                    "postgres",
                    "-c",
                    "max_connections=300",
                    "-c",
                    "fsync=off",
                    "-c",
                    "synchronous_commit=off",
                    "-c",
                    "full_page_writes=off",
                ]
            )
            .as_service()
        )

    @function
    def redis_service(self) -> dagger.Service:
        """Start a Redis 7 service container with 32 databases for xdist worker isolation."""
        return (
            dag.container()
            .from_(_REDIS_IMAGE)
            .with_exposed_port(6379)
            .with_default_args(
                ["redis-server", "--databases", "32", "--save", "", "--appendonly", "no"]
            )
            .as_service()
        )

    @function
    def mongo_service(self) -> dagger.Service:
        """Start a MongoDB 7 service container."""
        return (
            dag.container()
            .from_(_MONGO_IMAGE)
            .with_env_variable("MONGO_INITDB_ROOT_USERNAME", "gaia")
            .with_env_variable("MONGO_INITDB_ROOT_PASSWORD", "gaia")
            .with_exposed_port(27017)
            .as_service()
        )

    @function
    def chroma_service(self) -> dagger.Service:
        """Start a ChromaDB service container."""
        return dag.container().from_(_CHROMA_IMAGE).with_exposed_port(8000).as_service()

    @function
    def rabbitmq_service(self) -> dagger.Service:
        """Start a RabbitMQ 3 service container."""
        return dag.container().from_(_RABBITMQ_IMAGE).with_exposed_port(5672).as_service()

    def _service_test_container(self, source: Source) -> dagger.Container:
        """Create a test container wired to all live service containers.

        Services: PostgreSQL, Redis, MongoDB, ChromaDB, RabbitMQ.
        Credentials are injected via dagger.Secret so they never appear in
        build logs or the Dagger TUI.
        USE_REAL_SERVICES=1 tells conftest to skip infrastructure mocks and
        use real connections instead.
        """
        pg = self.postgres_service()
        redis = self.redis_service()
        mongo = self.mongo_service()
        chroma = self.chroma_service()
        rabbitmq = self.rabbitmq_service()
        return (
            self.ci_env(source)
            .with_service_binding("postgres", pg)
            .with_service_binding("redis", redis)
            .with_service_binding("mongo", mongo)
            .with_service_binding("chroma", chroma)
            .with_service_binding("rabbitmq", rabbitmq)
            .with_env_variable("ENV", "test")
            .with_env_variable("USE_REAL_SERVICES", "1")
            .with_env_variable("CHROMADB_HOST", "chroma")
            .with_env_variable("CHROMADB_PORT", "8000")
            .with_secret_variable(
                "DATABASE_URL",
                dag.set_secret(
                    "db-url",
                    "postgresql://gaia:gaia@postgres:5432/gaia_test",  # pragma: allowlist secret
                ),
            )
            # POSTGRES_URL is the env var that settings.POSTGRES_URL reads (Pydantic
            # field). Memory tests (tests/memory/conftest.py) read settings.POSTGRES_URL
            # directly, so it must be set in addition to DATABASE_URL (which the
            # integration/service/e2e conftest reads via os.environ directly).
            .with_secret_variable(
                "POSTGRES_URL",
                dag.set_secret(
                    "postgres-url",
                    "postgresql://gaia:gaia@postgres:5432/gaia_test",  # pragma: allowlist secret
                ),
            )
            .with_secret_variable(
                "REDIS_URL",
                dag.set_secret("redis-url", "redis://redis:6379/0"),
            )
            .with_secret_variable(
                "MONGODB_URL",
                dag.set_secret(
                    "mongo-url",
                    "mongodb://gaia:gaia@mongo:27017/gaia_test?authSource=admin",  # pragma: allowlist secret
                ),
            )
            # MONGO_DB is the env var that app/db/mongodb/mongodb.py reads via
            # settings.MONGO_DB. Must match MONGODB_URL so _get_mongodb_instance()
            # and the service test fixtures both hit the same database.
            .with_secret_variable(
                "MONGO_DB",
                dag.set_secret(
                    "mongo-db-url",
                    "mongodb://gaia:gaia@mongo:27017/gaia_test?authSource=admin",  # pragma: allowlist secret
                ),
            )
            .with_secret_variable(
                "RABBITMQ_URL",
                dag.set_secret(
                    "rabbitmq-url",
                    "amqp://guest:guest@rabbitmq/",  # pragma: allowlist secret
                ),
            )
            .with_workdir("/app/apps/api")
        )

    @function
    async def integration_test(self, source: Source) -> str:
        """Run all non-composio tests with full live service containers.

        This is the comprehensive test pass: unit + integration + e2e + service,
        all wired to real Postgres, Redis, MongoDB, ChromaDB, and RabbitMQ.
        """
        return await (
            self._service_test_container(source)
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-m",
                    "not composio",
                    "--tb=short",
                    "-q",
                    "--override-ini=addopts=--strict-markers",
                ]
            )
            .stdout()
        )

    @function
    async def service_test(self, source: Source) -> str:
        """Run service + integration + e2e tests with live containers.

        All real-infrastructure tests: Postgres, Redis, MongoDB, ChromaDB, RabbitMQ.
        """
        return await (
            self._service_test_container(source)
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-m",
                    "service or integration or e2e",
                    "--tb=short",
                    "-v",
                    "--override-ini=addopts=--strict-markers",
                ]
            )
            .stdout()
        )

    # ── Docker image builds ────────────────────────────────────────

    @function
    async def docker_build(
        self,
        source: Source,
        app: Annotated[
            str,
            Doc("App to build: api, web, voice-agent, bot-discord, bot-slack, bot-telegram"),
        ],
    ) -> dagger.Container:
        """Build a production Docker image for the specified app using its Dockerfile."""
        dockerfile_map: dict[str, tuple[str, list[dagger.BuildArg]]] = {
            "api": ("apps/api/Dockerfile", []),
            "web": (
                "apps/web/Dockerfile",
                [
                    dagger.BuildArg(
                        name="NEXT_PUBLIC_API_BASE_URL",
                        value="http://localhost:8000/api/v1/",
                    )
                ],
            ),
            "voice-agent": ("apps/voice-agent/Dockerfile", []),
            "bot-discord": (
                "apps/bots/Dockerfile",
                [dagger.BuildArg(name="BOT_NAME", value="discord")],
            ),
            "bot-slack": (
                "apps/bots/Dockerfile",
                [dagger.BuildArg(name="BOT_NAME", value="slack")],
            ),
            "bot-telegram": (
                "apps/bots/Dockerfile",
                [dagger.BuildArg(name="BOT_NAME", value="telegram")],
            ),
        }

        if app not in dockerfile_map:
            msg = f"Unknown app '{app}'. Valid: {', '.join(sorted(dockerfile_map))}"
            raise ValueError(msg)

        dockerfile, build_args = dockerfile_map[app]

        return source.docker_build(
            dockerfile=dockerfile,
            build_args=build_args,
        )

    @function
    async def docker_build_all(self, source: Source) -> str:
        """Build all production Docker images in parallel."""
        apps = ["api", "web", "voice-agent", "bot-discord", "bot-slack", "bot-telegram"]
        results = await asyncio.gather(
            *[self.docker_build(source, app=app) for app in apps],
            return_exceptions=True,
        )
        lines = []
        for app, result in zip(apps, results):
            if isinstance(result, Exception):
                lines.append(f"  {app}: FAILED ({result})")
            else:
                lines.append(f"  {app}: OK")
        return "Docker build results:\n" + "\n".join(lines)

    # ── Orchestrated gates ───────────────────────────────────────

    @function
    async def quality_checks(self, source: Source) -> str:
        """Run the full quality gate with bounded local CPU use.

        CI schedules these checks across separate runners. A local Mac runs them one at a
        time, with Nx at one job and Python tests capped at two workers, so the gate does
        not saturate the machine.
        """
        env = self.ci_env(source)

        lint_task = env.with_exec(["npx", "nx", "run-many", "-t", "lint", "--parallel=1"]).stdout()

        type_check_task = (
            env.with_workdir("/app/apps/api")
            .with_exec(["uv", "run", "mypy", "app", "--ignore-missing-imports"])
            .with_workdir("/app")
            .with_exec(["npx", "nx", "run-many", "-t", "type-check", "--parallel=1"])
            .stdout()
        )

        build_task = (
            env.with_env_variable(
                "NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com"
            )
            .with_env_variable("GAIA_BUILD_WORKERS", "2")
            .with_exec(["npx", "nx", "run-many", "-t", "build", "--parallel=1"])
            .stdout()
        )

        test_python_task = self.test_python(source, worker_limit=2)
        test_typescript_task = self.test_typescript(source, parallelism=1)

        dead_code_task = (
            env.with_exec(["uv", "tool", "install", "vulture"])
            .with_env_variable(
                "PATH",
                "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            )
            .with_exec(["bash", "scripts/dead-code-check.sh"])
            .stdout()
        )

        validate_task = env.with_exec(["node", "scripts/ci/release.mjs", "validate-manifest"]).stdout()

        trivy_task = (
            dag.container()
            .from_("ghcr.io/aquasecurity/trivy:latest")
            .with_directory("/src", source)
            # Entrypoint is `trivy`, so args start after it.
            # Scan the repo root so uv.lock (at root) and pyproject.toml are
            # reachable. Skip node_modules/venvs to keep it fast.
            # expect=ANY: informational scan — never fail CI.
            .with_exec(
                [
                    "filesystem",
                    "--severity",
                    "CRITICAL,HIGH",
                    "--format",
                    "table",
                    "--skip-dirs",
                    "node_modules,.venv,dist,.next,out",
                    "/src",
                ],
                expect=dagger.ReturnType.ANY,
            )
            .stdout()
        )

        tasks = (
            lint_task,
            type_check_task,
            build_task,
            test_python_task,
            test_typescript_task,
            dead_code_task,
            validate_task,
            trivy_task,
        )

        labels = [
            "LINT",
            "TYPE-CHECK",
            "BUILD",
            "TESTS (python)",
            "TESTS (typescript)",
            "DEAD-CODE",
            "RELEASE-VALIDATION",
            "TRIVY-SCAN",
        ]
        results: list[str] = []
        failures: list[str] = []
        for label, task in zip(labels, tasks):
            try:
                results.append(await task)
            except Exception as exc:
                failures.append(f"{label}: {exc}")
                results.append(f"FAILED: {exc}")

        sections = []
        for label, output in zip(labels, results):
            sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")

        report = "\n\n".join(sections)
        if failures:
            failure_summary = "\n".join(failures)
            raise RuntimeError(f"Quality checks failed:\n{failure_summary}\n\n{report}")
        return report
