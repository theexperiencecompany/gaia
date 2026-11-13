"""Fixtures for the contract invariants: one app, shared by every meta module."""

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
import pytest

from app.core.app_factory import create_app


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
def all_routes(app: FastAPI) -> list[RouteContext]:
    """Every APIRoute, documented or not — a hidden alias shares the id namespace."""
    return [
        ctx for ctx in iter_route_contexts(app.routes) if isinstance(ctx.original_route, APIRoute)
    ]


@pytest.fixture(scope="session")
def routes(all_routes: list[RouteContext]) -> list[RouteContext]:
    """Keep the documented routes — what the OpenAPI document and the types carry."""
    return [ctx for ctx in all_routes if ctx.original_route.include_in_schema]
