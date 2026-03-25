"""Dagger CI/CD pipeline for the GAIA monorepo.

Provides containerized quality checks and Docker image build/publish
functions that run identically locally and in CI.
"""

from typing import Annotated

import dagger
from dagger import Doc, DefaultPath, Ignore, dag, function, object_type

# Patterns excluded from the source context for all functions.
# Keep this tight — unnecessary files slow down the filesync to the engine.
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


@object_type
class GaiaCi:
    """CI/CD pipeline for the GAIA monorepo."""

    @function
    def ci_env(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> dagger.Container:
        """Create a full CI environment with Node.js 22, Python 3.12, pnpm, and uv."""
        pnpm_cache = dag.cache_volume("pnpm-store")
        uv_cache = dag.cache_volume("uv-cache")
        nx_cache = dag.cache_volume("nx-cache")
        return (
            dag.container()
            .from_("node:22.15.1-bookworm-slim")
            # Install Python 3.12, git, and build essentials
            .with_exec([
                "apt-get", "update",
            ])
            .with_exec([
                "apt-get", "install", "-y", "--no-install-recommends",
                "python3", "python3-pip", "python3-venv", "python3-dev",
                "git", "curl", "build-essential", "libpq-dev",
            ])
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
            .with_mounted_cache("/app/.nx/cache", nx_cache)
            # Copy source and install deps
            .with_directory("/app", source)
            .with_workdir("/app")
            .with_exec(["pnpm", "install", "--frozen-lockfile"])
            .with_exec(["uv", "sync", "--frozen", "--package", "gaia", "--group", "backend", "--group", "dev"])
        )

    @function
    async def lint(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> str:
        """Run linting across the monorepo (Biome for JS/TS, Ruff for Python)."""
        return await (
            self.ci_env(source)
            .with_exec(["npx", "nx", "run-many", "-t", "lint", "--parallel=3"])
            .stdout()
        )

    @function
    async def type_check(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> str:
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
    async def build(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> str:
        """Build all projects."""
        return await (
            self.ci_env(source)
            .with_env_variable("NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com")
            .with_exec(["npx", "nx", "run-many", "-t", "build", "--parallel=3"])
            .stdout()
        )

    @function
    async def test(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> str:
        """Run all tests (JS/TS via Nx + Python via pytest)."""
        return await (
            self.ci_env(source)
            .with_env_variable("ENV", "test")
            .with_exec(["npx", "nx", "run-many", "-t", "test", "--parallel=3"])
            .with_workdir("/app/apps/api")
            .with_exec([
                "uv", "run", "pytest",
                "-m", "not integration and not composio",
                "--tb=short", "-q",
                "--cov=app", "--cov-report=term-missing",
                "--cov-fail-under=80",
            ])
            .stdout()
        )

    @function
    async def quality_checks(
        self,
        source: Annotated[
            dagger.Directory,
            DefaultPath("/"),
            Ignore(_IGNORE),
            Doc("Repository source directory"),
        ],
    ) -> str:
        """Run the full quality gate: lint, type-check, build, and test."""
        env = self.ci_env(source)
        return await (
            env
            .with_env_variable("NEXT_PUBLIC_API_BASE_URL", "http://fake-api-for-build.example.com")
            .with_env_variable("ENV", "test")
            # Install mypy types
            .with_workdir("/app/apps/api")
            .with_exec(["uv", "run", "mypy", "--install-types", "--non-interactive"])
            .with_workdir("/app")
            # Install dead code tools
            .with_exec(["uv", "tool", "install", "vulture"])
            # Run all Nx quality targets
            .with_exec(["npx", "nx", "run-many", "-t", "lint", "type-check", "build", "test", "--parallel=3"])
            # Run Python tests
            .with_workdir("/app/apps/api")
            .with_exec([
                "uv", "run", "pytest",
                "-m", "not integration and not composio",
                "--tb=short", "-q",
                "--cov=app", "--cov-report=term-missing",
                "--cov-fail-under=80",
            ])
            .stdout()
        )
