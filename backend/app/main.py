"""
StormHaven FastAPI entrypoint.   Owner: Nandan
Run:  make api   (or: cd backend && uvicorn app.main:app --reload)
Docs at http://localhost:8000/docs  (frontend team: this is the contract)
"""
from __future__ import annotations
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

load_dotenv()      # read .env BEFORE importing app modules, so Bedrock/SNS settings are visible to them

from app.ai.agent import chat                                   # noqa: E402
from app.console import router as console_router              # noqa: E402
from app.notify.router import router as notify_router         # noqa: E402  (Abby: POST /api/notify)
from app.core.data_loader import get_store                      # noqa: E402
from app.map_layers import map_layers                           # noqa: E402
from app.planner_routes import router as planner_router        # noqa: E402
from app.schemas import ChatRequest, ConciergeRequest, ConciergeResponse  # noqa: E402
from app.service import run_concierge                           # noqa: E402
from app.weather import weather_context                         # noqa: E402

app = FastAPI(title="StormHaven API", version="0.1.0")
# Open CORS so a separately hosted frontend (Amplify) can call the API. Tighten to the real origin at deploy.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Compress responses over 1 KB: the real-data map payload is several MB of numbers and shrinks ~5-10x.
app.add_middleware(GZipMiddleware, minimum_size=1000)
# Utility operator console (read-only, GET /api/console/*): app/console.py.
app.include_router(console_router)
# Storm restoration planner (read-only, GET /api/planner/*): app/planner_routes.py + engines/planner.py.
app.include_router(planner_router)
# Proactive-alert sender (POST /api/notify): app/notify/router.py. Dry-runs unless SNS is configured.
app.include_router(notify_router)


@app.get("/api/health")
def health():
    """Liveness + which data is loaded. The frontend shows a 'synthetic data' banner from this."""
    s = get_store()
    return {"ok": True, "synthetic_data": s.is_synthetic, "labor_from_aep": s.labor_from_aep,
            "nodes": s.graph.number_of_nodes(), "notes": s.notes}


@app.post("/api/concierge", response_model=ConciergeResponse)
def concierge(req: ConciergeRequest):
    """Everything for one location: risk + restoration + guidance + alerts."""
    return run_concierge(req)


@app.get("/api/map")
def get_map(severity: float = 50):
    """Map layers for Plotly: circuit lines + premise points colored by risk band."""
    return map_layers(severity)


@app.get("/api/weather")
def get_weather():
    """Weather context: reference storms (slider labels), damage odds by wind, live 3-day forecast + NWS alerts.
    Context only: weather never changes a risk or restoration number."""
    return weather_context()

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    """One chat turn. The reply is already scrubbed; numbers in it come only from the engines."""
    history = [message.model_dump() for message in req.history]
    return {"reply": chat(history, req.premise_id, req.circuit_id, req.scenario,
                          req.profile, req.utility_status)}
