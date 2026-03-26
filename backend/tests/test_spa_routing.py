"""
Regression test: Render static site must rewrite all SPA paths to /index.html.

Bug: render.yaml had no `routes` section. The `_redirects` file in frontend/public
is Netlify format and is silently ignored by Render, so every path except / returned
"Not Found" instead of serving the React app.

Fix: add `routes` with a catch-all rewrite to the static site entry in render.yaml.
"""
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent  # backend/tests/ → backend/ → smeta-ai/
RENDER_YAML = REPO_ROOT / "render.yaml"


def _render_yaml_text() -> str:
    assert RENDER_YAML.exists(), f"render.yaml not found at {RENDER_YAML}"
    return RENDER_YAML.read_text()


def test_render_yaml_has_spa_rewrite_route():
    """Static site in render.yaml must rewrite /* to /index.html (type: rewrite).

    Without this, React Router paths like /admin, /projects, /login all 404
    because Render's static site has no file at those paths and no fallback rule.
    The _redirects file in frontend/public/ is Netlify format — Render ignores it.
    """
    content = _render_yaml_text()

    assert "type: rewrite" in content, (
        "render.yaml is missing a rewrite route for the static site. "
        "Add under the static service:\n"
        "  routes:\n"
        "    - type: rewrite\n"
        "      source: /*\n"
        "      destination: /index.html"
    )
    assert "source: /*" in content, (
        "render.yaml rewrite route must use 'source: /*' to catch all SPA paths."
    )
    assert "destination: /index.html" in content, (
        "render.yaml rewrite route must send all paths to 'destination: /index.html'."
    )
