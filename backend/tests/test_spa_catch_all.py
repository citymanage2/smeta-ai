"""
Regression test: FastAPI backend must serve index.html for all unknown paths.

Bug: GET /projects, /tasks/<uuid>, etc. returned 404 because FastAPI has no
catch-all route — React Router only works client-side, so a hard refresh (F5)
sends the path to the server which has no handler for it.

Fix: catch-all @app.get("/{full_path:path}") after all API routers that returns
index.html из собранного фронта (`settings.FRONTEND_DIST_DIR`). Тест подкладывает
свой index.html: собранного `frontend/dist` на чистом клоне нет (он в .gitignore).
"""
import pytest
from httpx import AsyncClient

from app.config import settings

# These are React Router paths that have NO corresponding API GET endpoint.
# /projects and /projects/{id} are real API routes (return 401 without auth)
# and correctly take precedence over the catch-all — that's expected.
SPA_PATHS = [
    "/login",
    "/tasks/a1000000-0000-0000-0000-000000000001",  # GET /tasks/{id} is not a registered route
    "/some-unknown-page",
    "/deep/nested/route",
]

INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'


@pytest.fixture
def spa_dist(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    monkeypatch.setattr(settings, "FRONTEND_DIST_DIR", str(tmp_path))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", SPA_PATHS)
async def test_spa_path_returns_html(spa_dist, async_client: AsyncClient, path: str):
    """Catch-all route must return the React app shell itself."""
    resp = await async_client.get(path)
    assert resp.status_code == 200, (
        f"GET {path} returned {resp.status_code}, expected 200. "
        "FastAPI must have a catch-all route serving index.html."
    )
    assert "text/html" in resp.headers.get("content-type", "")
    assert resp.text == INDEX_HTML
