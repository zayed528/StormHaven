"""
StormHaven FastAPI entrypoint.   Owner: Nandan
Run:  make api   (or: cd backend && uvicorn app.main:app --reload)
Docs at http://localhost:8000/docs  (frontend team: this is the contract)
"""
from __future__ import annotations
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

load_dotenv()      # read .env BEFORE importing app modules, so Bedrock/SNS settings are visible to them

from app.ai.agent import chat                                   # noqa: E402
from app.console import router as console_router              # noqa: E402
from app.notify.router import router as notify_router         # noqa: E402  (Abby: POST /api/notify)
from app.locate import router as locate_router               # noqa: E402  (Abby: GET /api/locate)
from app.core.data_loader import get_store                      # noqa: E402
from app.map_layers import map_layers                           # noqa: E402
from app.planner_routes import router as planner_router        # noqa: E402
from app.schemas import ChatRequest, ConciergeRequest, ConciergeResponse  # noqa: E402
from app.service import run_concierge                           # noqa: E402
from app.weather import weather_context                         # noqa: E402
from app.public_demo import enabled as public_demo_enabled, require_demo_location, validate_environment  # noqa: E402

_PUBLIC_DEMO = public_demo_enabled()
app = FastAPI(title="StormHaven API", version="0.1.0",
              docs_url=None if _PUBLIC_DEMO else "/docs",
              redoc_url=None if _PUBLIC_DEMO else "/redoc",
              openapi_url=None if _PUBLIC_DEMO else "/openapi.json")


@app.on_event("startup")
def enforce_public_demo_boundary():
    """Also protect direct uvicorn starts that do not use app.startup's container preflight."""
    if _PUBLIC_DEMO:
        validate_environment()
        if not get_store().is_synthetic:
            raise RuntimeError("Public demo startup failed: non-synthetic data is loaded")


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _cors_origins() -> list[str]:
    configured = [origin.strip() for origin in os.getenv("STORMHAVEN_CORS_ORIGINS", "").split(",") if origin.strip()]
    if _env_enabled("STORMHAVEN_PRODUCTION"):
        if not configured or "*" in configured:
            raise RuntimeError("STORMHAVEN_CORS_ORIGINS must contain explicit origins in production")
        return configured
    return configured or ["http://localhost:5173"]


app.add_middleware(CORSMiddleware, allow_origins=_cors_origins(), allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Content-Type", "Authorization"])
# Compress responses over 1 KB: the real-data map payload is several MB of numbers and shrinks ~5-10x.
app.add_middleware(GZipMiddleware, minimum_size=1000)
# Operator and notification routes are disabled unless explicitly enabled behind an authenticated boundary.
if not _PUBLIC_DEMO and _env_enabled("STORMHAVEN_ENABLE_OPERATOR_ROUTES"):
    app.include_router(console_router)
    app.include_router(planner_router)
if not _PUBLIC_DEMO and _env_enabled("STORMHAVEN_ENABLE_NOTIFY"):
    app.include_router(notify_router)
# Onboarding location lookup (GET /api/locate): app/locate.py. Premise ID / geolocation -> neighborhood zoom.
app.include_router(locate_router)


@app.get("/api/health")
def health():
    """Liveness + which data is loaded. The frontend shows a 'synthetic data' banner from this."""
    s = get_store()
    if _PUBLIC_DEMO:
        return {"ok": True, "mode": "public_demo"}
    return {"ok": True, "synthetic_data": s.is_synthetic, "labor_from_aep": s.labor_from_aep,
            "nodes": s.graph.number_of_nodes(), "notes": s.notes}


@app.post("/api/concierge", response_model=ConciergeResponse)
def concierge(req: ConciergeRequest):
    """Everything for one location: risk + restoration + guidance + alerts."""
    require_demo_location(get_store(), req.premise_id, req.circuit_id)
    return run_concierge(req)


@app.get("/api/map")
def get_map(severity: float = 50):
    """Map layers for Plotly: circuit lines + premise points colored by risk band."""
    return map_layers(severity)


if not _PUBLIC_DEMO:
    @app.get("/api/weather")
    def get_weather():
        """Weather context only; it never changes a risk or restoration number."""
        return weather_context()

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    """One chat turn. The reply is already scrubbed; numbers in it come only from the engines."""
    require_demo_location(get_store(), req.premise_id, req.circuit_id)
    history = [message.model_dump() for message in req.history]
    return {"reply": chat(history, req.premise_id, req.circuit_id, req.scenario,
                          req.profile, req.utility_status)}
