"""Graph helpers. Everything about 'who feeds whom' goes through here.   Owner: Jaid"""
from __future__ import annotations
import networkx as nx
from app.core.data_loader import DataStore

# Node kinds that are equipment (everything except "premise"). Order upstream -> downstream.
DEVICE_KINDS = {"substation", "breaker", "recloser", "fuse", "step_transformer", "transformer"}


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


def map_point_for(store: DataStore, transformer_id: str) -> str | None:
    """The premise ID used as a transformer's map dot: the lowest-sorting premise it serves.
    map_layers.py draws exactly these, and the concierge reports it so the UI can ring the right dot."""
    g = store.graph
    homes = sorted(c for c in g.successors(transformer_id) if g.nodes[c]["kind"] == "premise")
    return homes[0] if homes else None


def premises_on_circuit(store: DataStore, circuit_id: str) -> list[str]:
    """All premise node IDs whose circuit_id matches. Linear scan: fine at hackathon scale."""
    g = store.graph
    return [n for n, d in g.nodes(data=True) if d["kind"] == "premise" and d["circuit_id"] == circuit_id]


def resolve_location(store: DataStore, premise_id: str | None, circuit_id: str | None):
    """Returns (level, node_id). Premise > circuit representative > none (fallback)."""
    g = store.graph
    # Exact premise match is the most precise answer.
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
