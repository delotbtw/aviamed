from pathlib import Path

from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent.parent


def _asset_version() -> str:
    """Cache-busting token for css/js: changes whenever a static file does."""
    files = [p for pattern in ("css/*.css", "js/*.js") for p in (APP_DIR / "static").glob(pattern)]
    return format(max((p.stat().st_mtime_ns for p in files), default=0) // 1_000_000, "x")


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals["asset_version"] = _asset_version()
