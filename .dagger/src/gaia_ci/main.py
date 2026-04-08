"""Dagger CI/CD pipeline for the GAIA monorepo.

Provides containerized quality checks and Docker image build/publish
functions that run identically locally and in CI.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import dagger
from dagger import Doc, DefaultPath, Ignore, dag, function, object_type

# Patterns excluded from the source context for all functions.
# Keep this tight -- unnecessary files slow down the filesync to the engine.
_IGNORE = [
    "node_modules",
    ".conductor",
    ".next",
    "__pycache__",
    ".venv",
    "dist",
    ".nx/cache",
    ".nx/workspace-data",
    ".pnpm-store",
    "chroma-data",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "coverage",
    ".wwebjs_auth",
    ".wwebjs_cache",
    ".hypothesis",
    "out",
    ".agents/plans",
]

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
                    "apt-get update"
                    " && apt-get install -y --no-install-recommends"
                    " python3 python3-pip python3-venv python3-dev"
                    " git curl build-essential libpq-dev"
                    " && apt-get clean"
                    " && rm -rf /var/lib/apt/lists/*",
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
                    "libs/**",
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
            .with_env_variable(
                "NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com"
            )
            .with_exec(["npx", "nx", "run-many", "-t", "build", "--parallel=3"])
            .stdout()
        )

    @function
    async def test(self, source: Source) -> str:
        """Run all tests (Python + TypeScript). Local convenience wrapper."""
        py_task = self.test_python(source)
        ts_task = self.test_typescript(source)
        results = await asyncio.gather(py_task, ts_task)
        labels = ["PYTHON TESTS", "TYPESCRIPT TESTS"]
        sections = []
        for label, output in zip(labels, results):
            sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")
        return "\n\n".join(sections)

    @function
    async def test_python(self, source: Source) -> str:
        """Run all Python tests with live service containers and pytest-xdist."""
        return await (
            self._service_test_container(source)
            .with_exec(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "pytest",
                    "-n",
                    "auto",
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
    async def test_python_coverage(self, source: Source) -> str:
        """Run all Python tests with live services and coverage reporting."""
        return await (
            self._service_test_container(source)
            .with_exec(
                [
                    "uv",
                    "run",
                    "--frozen",
                    "pytest",
                    "-n",
                    "auto",
                    "-m",
                    "not composio",
                    "--tb=short",
                    "-q",
                    "--cov=app",
                    "--cov-report=term-missing",
                    "--cov-fail-under=80",
                    "--override-ini=addopts=--strict-markers",
                ]
            )
            .stdout()
        )

    @function
    async def test_typescript(self, source: Source, projects: str = "") -> str:
        """Run JS/TS tests via Nx. Pass projects= to scope to specific projects."""
        cmd = ["npx", "nx", "run-many", "-t", "test", "--parallel=3"]
        if projects:
            cmd.extend(["-p", projects])
        return await (
            self.ci_env(source).with_env_variable("ENV", "test").with_exec(cmd).stdout()
        )

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
            .with_exec(["node", "scripts/ci/validate-release-manifest.mjs"])
            .stdout()
        )

    # ── Service containers (for integration tests) ───────────────

    @function
    def postgres_service(self) -> dagger.Service:
        """Start a PostgreSQL 16 service container."""
        return (
            dag.container()
            .from_("postgres:16-alpine")
            .with_env_variable("POSTGRES_USER", "gaia")
            .with_env_variable("POSTGRES_PASSWORD", "gaia")
            .with_env_variable("POSTGRES_DB", "gaia_test")
            .with_exposed_port(5432)
            .as_service()
        )

    @function
    def redis_service(self) -> dagger.Service:
        """Start a Redis 7 service container with 32 databases for xdist worker isolation."""
        return (
            dag.container()
            .from_("redis:7-alpine")
            .with_exposed_port(6379)
            .with_exec(["redis-server", "--databases", "32"])
            .as_service()
        )

    @function
    def mongo_service(self) -> dagger.Service:
        """Start a MongoDB 7 service container."""
        return (
            dag.container()
            .from_("mongo:7")
            .with_env_variable("MONGO_INITDB_ROOT_USERNAME", "gaia")
            .with_env_variable("MONGO_INITDB_ROOT_PASSWORD", "gaia")
            .with_exposed_port(27017)
            .as_service()
        )

    @function
    def chroma_service(self) -> dagger.Service:
        """Start a ChromaDB service container."""
        return (
            dag.container()
            .from_("chromadb/chroma:latest")
            .with_exposed_port(8000)
            .as_service()
        )

    @function
    def rabbitmq_service(self) -> dagger.Service:
        """Start a RabbitMQ 3 service container."""
        return (
            dag.container()
            .from_("rabbitmq:3-alpine")
            .with_exposed_port(5672)
            .as_service()
        )

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
            Doc(
                "App to build: api, web, voice-agent, bot-discord, bot-slack, bot-telegram"
            ),
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
        """Run the full quality gate in parallel. Local convenience — mirrors what CI runs."""
        env = self.ci_env(source)

        # Run all checks concurrently. Dagger deduplicates the shared ci_env
        # container automatically -- each branch forks from the cached base.
        lint_task = env.with_exec(
            ["npx", "nx", "run-many", "-t", "lint", "--parallel=3"]
        ).stdout()

        type_check_task = (
            env.with_workdir("/app/apps/api")
            .with_exec(["uv", "run", "mypy", "app", "--ignore-missing-imports"])
            .with_workdir("/app")
            .with_exec(["npx", "nx", "run-many", "-t", "type-check", "--parallel=3"])
            .stdout()
        )

        build_task = (
            env.with_env_variable(
                "NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com"
            )
            .with_exec(["npx", "nx", "run-many", "-t", "build", "--parallel=3"])
            .stdout()
        )

        test_python_task = self.test_python(source)
        test_typescript_task = self.test_typescript(source)

        dead_code_task = (
            env.with_exec(["uv", "tool", "install", "vulture"])
            .with_env_variable(
                "PATH",
                "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            )
            .with_exec(["bash", "scripts/dead-code-check.sh"])
            .stdout()
        )

        validate_task = env.with_exec(
            ["node", "scripts/ci/validate-release-manifest.mjs"]
        ).stdout()

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

        results = await asyncio.gather(
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
        sections = []
        for label, output in zip(labels, results):
            sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")

        return "\n\n".join(sections)
