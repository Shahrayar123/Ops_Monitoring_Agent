"""The product's FastAPI application.

Run from the repo root:

    uvicorn backend.app.main:app --port 8080 --reload

Interactive docs at http://127.0.0.1:8080/docs
"""

import logging
import sys
from pathlib import Path

# Repo root on the path so the engine packages (checks/, data_sources/, ...)
# and `backend.app` resolve no matter where uvicorn was launched from.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import get_settings
from backend.app.core.errors import install_error_handling
from backend.app.api.routes import admin, analysis, auth, kpi_settings, monitoring, plans_admin, tenant_admin, user_admin
from backend.app.api.routes import settings as settings_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="2.0",
    description="Cloudera cluster monitoring with governed AI incident analysis.",
)

install_error_handling(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(monitoring.router)
app.include_router(tenant_admin.router)
app.include_router(settings_routes.router)
app.include_router(kpi_settings.router)
app.include_router(plans_admin.router)
app.include_router(user_admin.router)
app.include_router(analysis.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
