"""Graph helpers. Everything about 'who feeds whom' goes through here.   Owner: Jaid"""
from __future__ import annotations
import hashlib

import networkx as nx
from app.core.data_loader import DataStore

# Node kinds that are equipment (everything except "premise"). Order upstream -> downstream.
DEVICE_KINDS = {"substation", "breaker", "recloser", "fuse", "step_transformer", "transformer"}

# --- Anonymous map tokens (privacy) --------------------------------------------------------------------------
# The map and /api/locate must NOT leak real premise numbers (an account ID) — 1/3 of transformers serve a
# single home, so a real premise ID + an 11 m coordinate would pinpoint a house. So each map dot is an
# ANONYMOUS token derived from its TRANSFORMER, e.g. "N-1a2b3". The token round-trips: the backend maps it back
# to the transformer, then to a representative premise, for the actual risk/restoration computation. Real
# premise numbers are used ONLY when a customer deliberately types their own ID. Tokens are stable (a hash of
# the transformer id), so the same dot keeps the same token across requests.
TOKEN_PREFIX = "N-"


def token_for(transformer_id: str) -> str:
    """Stable anonymous token for a transformer's map dot. Deterministic hash -> no real id is exposed."""
    h = hashlib.sha1(transformer_id.encode()).hexdigest()[:5]
    return f"{TOKEN_PREFIX}{h}"


# token -> transformer, built once per store. Keyed by id(store) because DataStore isn't hashable
# (same pattern the restoration engine uses for its priority cache).
_TOKEN_CACHE: dict[int, dict[str, str]] = {}


def _token_to_transformer(store: DataStore) -> dict[str, str]:
    """token -> transformer node id for this store, built once and cached."""
    key = id(store)
    if key not in _TOKEN_CACHE:
        g = store.graph
        _TOKEN_CACHE[key] = {token_for(n): n for n, d in g.nodes(data=True) if d.get("kind") == "transformer"}
    return _TOKEN_CACHE[key]


def transformer_for_token(store: DataStore, token: str) -> str | None:
    """Reverse a map token back to its transformer node id, or None if it isn't a known token."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    return _token_to_transformer(store).get(token)


def upline_path(store: DataStore, node_id: str) -> list[str]:
    """Equipment between this premise and the substation, NEAREST FIRST.
    Premise loses power if ANY of these fails; restored when ALL are fixed."""
    g = store.graph
    path, cur = [], node_id
    # Walk parent links (edges point parent -> child, i.e. the direction power flows) until the root.
    while True:
        parents = list(g.predecessors(cur))
        if not parents:
            break
        cur = parents[0]          # radial distribution: one parent. TODO: handle ties/loops if real data has them
        path.append(cur)
    return path


def _representative_premise(store: DataStore, transformer_id: str) -> str | None:
    """The lowest-sorting premise a transformer serves. Used INTERNALLY to pick which real premise the engine
    computes on for a dot; its id never leaves the backend (the dot shows a token instead)."""
    g = store.graph
    homes = sorted(c for c in g.successors(transformer_id) if g.nodes[c]["kind"] == "premise")
    return homes[0] if homes else None


def map_point_for(store: DataStore, transformer_id: str) -> str | None:
    """The ANONYMOUS token used as a transformer's map dot (not a premise number — privacy).
    map_layers.py draws these tokens, /api/locate returns them, and the concierge rings the clicked one.
    Returns None only if the transformer serves no premise (so there's nothing to show)."""
    if _representative_premise(store, transformer_id) is None:
        return None
    return token_for(transformer_id)


def premises_on_circuit(store: DataStore, circuit_id: str) -> list[str]:
    """All premise node IDs whose circuit_id matches. Linear scan: fine at hackathon scale."""
    g = store.graph
    return [n for n, d in g.nodes(data=True) if d["kind"] == "premise" and d["circuit_id"] == circuit_id]


def resolve_location(store: DataStore, premise_id: str | None, circuit_id: str | None):
    """Returns (level, node_id). Accepts an anonymous map TOKEN (N-...), a real premise id, or a circuit id.
    Order: token/premise > circuit representative > none (fallback)."""
    g = store.graph
    # Anonymous map token (what a dot click sends): translate token -> transformer -> representative premise.
    # The customer never sees the premise id; this is only how the engine picks a real premise to compute on.
    if premise_id:
        xf = transformer_for_token(store, premise_id)
        if xf is not None:
            rep = _representative_premise(store, xf)
            if rep is not None:
                return "premise", rep
            return "none", None
    # Exact premise match (a customer typed their own id from the bill) is the most precise answer.
    if premise_id and premise_id in g and g.nodes[premise_id]["kind"] == "premise":
        return "premise", premise_id
    # Circuit only: answer for a typical premise on that circuit (risk engine lowers confidence for this).
    if circuit_id:
        prem = premises_on_circuit(store, circuit_id)
        if prem:
            # representative premise = median-depth premise on circuit
            prem.sort(key=lambda p: len(upline_path(store, p)))
            return "circuit", prem[len(prem) // 2]
    return "none", None       # unknown location -> every engine returns its fallback, never a guess
