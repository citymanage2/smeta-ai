"""
Regression test: FastAPI backend must serve index.html for all unknown paths.

Bug: GET /projects, /tasks/<uuid>, etc. returned 404 because FastAPI has no
catch-all route — React Router only works client-side, so a hard refresh (F5)
sends the path to the server which has no handler for it.

Fix: add catch-all @app.get("/{full_path:path}") after all API routers that
returns FileResponse("../frontend/dist/index.html").
"""
import pytest
from httpx import AsyncClient


# These are React Router paths that have NO corresponding API GET endpoint.
# /projects and /projects/{id} are real API routes (return 401 without auth)
# and correctly take precedence over the catch-all — that's expected.
SPA_PATHS = [
    "/login",
    "/tasks/a1000000-0000-0000-0000-000000000001",  # GET /tasks/{id} is not a registered route
    "/some-unknown-page",
    "/deep/nested/route",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SPA_PATHS)
async def test_spa_path_returns_200(async_client: AsyncClient, path: str):
    """Unknown frontend routes must return 200 with HTML (not 404)."""
    resp = await async_client.get(path)
    assert resp.status_code == 200, (
        f"GET {path} returned {resp.status_code}, expected 200. "
        "FastAPI must have a catch-all route serving index.html."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SPA_PATHS)
async def test_spa_path_returns_html(async_client: AsyncClient, path: str):
    """Catch-all route must return HTML content (the React app shell)."""
    resp = await async_client.get(path)
    content_type = resp.headers.get("content-type", "")
    assert "text/html" in content_type, (
        f"GET {path} returned Content-Type: {content_type!r}, expected text/html."
    )
