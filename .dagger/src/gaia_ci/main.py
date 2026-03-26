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
    def ci_env(self, source: Source) -> dagger.Container:
        """Create a full CI environment with Node.js 22, Python 3.12, pnpm, and uv."""
        pnpm_cache = dag.cache_volume("pnpm-store")
        uv_cache = dag.cache_volume("uv-cache")
        nx_cache = dag.cache_volume("nx-cache")
        next_cache = dag.cache_volume("next-cache")
        pip_cache = dag.cache_volume("pip-cache")
        return (
            dag.container()
            .from_("node:22.15.1-bookworm-slim")
            # Install Python 3.12, git, and build essentials
            .with_exec(["apt-get", "update"])
            .with_exec(
                [
                    "apt-get",
                    "install",
                    "-y",
                    "--no-install-recommends",
                    "python3",
                    "python3-pip",
                    "python3-venv",
                    "python3-dev",
                    "git",
                    "curl",
                    "build-essential",
                    "libpq-dev",
                ]
            )
            .with_exec(["apt-get", "clean"])
            .with_exec(["rm", "-rf", "/var/lib/apt/lists/*"])
            # Install pnpm via corepack
            .with_exec(["corepack", "enable"])
            .with_exec(["corepack", "prepare", "pnpm@10.17.1", "--activate"])
            # Install uv
            .with_exec(["pip", "install", "--break-system-packages", "uv"])
            # Mount caches
            .with_mounted_cache("/root/.local/share/pnpm/store", pnpm_cache)
            .with_mounted_cache("/root/.cache/uv", uv_cache)
            .with_mounted_cache("/root/.cache/pip", pip_cache)
            .with_mounted_cache("/app/.nx/cache", nx_cache)
            .with_mounted_cache("/app/apps/web/.next/cache", next_cache)
            # Copy source and install deps
            .with_directory("/app", source)
            .with_workdir("/app")
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
            .with_exec(["uv", "run", "mypy", "--install-types", "--non-interactive"])
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
        """Run all tests (JS/TS via Nx + Python via pytest)."""
        return await (
            self.ci_env(source)
            .with_env_variable("ENV", "test")
            .with_exec(["npx", "nx", "run-many", "-t", "test", "--parallel=3"])
            .with_workdir("/app/apps/api")
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-m",
                    "not integration and not composio",
                    "--tb=short",
                    "-q",
                    "--cov=app",
                    "--cov-report=term-missing",
                    "--cov-fail-under=80",
                ]
            )
            .stdout()
        )

    @function
    async def dead_code(self, source: Source) -> str:
        """Run dead code detection (vulture for Python, knip for TypeScript)."""
        return await (
            self.ci_env(source)
            .with_exec(["uv", "tool", "install", "vulture"])
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
        """Start a Redis 7 service container."""
        return (
            dag.container().from_("redis:7-alpine").with_exposed_port(6379).as_service()
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
    async def integration_test(self, source: Source) -> str:
        """Run integration tests with live service containers (Postgres, Redis, MongoDB)."""
        pg = self.postgres_service()
        redis = self.redis_service()
        mongo = self.mongo_service()
        return await (
            self.ci_env(source)
            .with_service_binding("postgres", pg)
            .with_service_binding("redis", redis)
            .with_service_binding("mongo", mongo)
            .with_env_variable("ENV", "test")
            .with_env_variable(
                "DATABASE_URL",
                "postgresql://gaia:gaia@postgres:5432/gaia_test",
            )
            .with_env_variable("REDIS_URL", "redis://redis:6379/0")
            .with_env_variable(
                "MONGODB_URL",
                "mongodb://gaia:gaia@mongo:27017/gaia_test?authSource=admin",
            )
            .with_workdir("/app/apps/api")
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-m",
                    "integration",
                    "--tb=short",
                    "-q",
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
        """Run the full quality gate in parallel: lint, type-check, build, test, dead-code, and release validation."""
        env = self.ci_env(source)

        # Run all checks concurrently. Dagger deduplicates the shared ci_env
        # container automatically -- each branch forks from the cached base.
        lint_task = env.with_exec(
            ["npx", "nx", "run-many", "-t", "lint", "--parallel=3"]
        ).stdout()

        type_check_task = (
            env.with_workdir("/app/apps/api")
            .with_exec(["uv", "run", "mypy", "--install-types", "--non-interactive"])
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

        test_task = (
            env.with_env_variable("ENV", "test")
            .with_exec(["npx", "nx", "run-many", "-t", "test", "--parallel=3"])
            .with_workdir("/app/apps/api")
            .with_exec(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-m",
                    "not integration and not composio",
                    "--tb=short",
                    "-q",
                    "--cov=app",
                    "--cov-report=term-missing",
                    "--cov-fail-under=80",
                ]
            )
            .stdout()
        )

        dead_code_task = (
            env.with_exec(["uv", "tool", "install", "vulture"])
            .with_exec(["bash", "scripts/dead-code-check.sh"])
            .stdout()
        )

        validate_task = env.with_exec(
            ["node", "scripts/ci/validate-release-manifest.mjs"]
        ).stdout()

        results = await asyncio.gather(
            lint_task,
            type_check_task,
            build_task,
            test_task,
            dead_code_task,
            validate_task,
        )

        labels = [
            "LINT",
            "TYPE-CHECK",
            "BUILD",
            "TEST",
            "DEAD-CODE",
            "RELEASE-VALIDATION",
        ]
        sections = []
        for label, output in zip(labels, results):
            sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")

        return "\n\n".join(sections)
