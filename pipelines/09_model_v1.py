"""
HOUR 9-14 (Akshat): risk model v1 (zone features) vs v0 (history + kind average), same honest backtest.
  python pipelines/09_model_v1.py           (after 03, 05, 08)

v1 = v0 with one change: for fuse / recloser / breaker zones, the average a device is pulled toward comes from a
Poisson regression on its zone's exposure (poles, transformers, overhead km, underground share; from
08_features.py) instead of one number per device kind. See pipelines/_rates.py -> fit_rates_v1.

Backtest: leave one storm out; re-fit BOTH models (including v1's regression) without it; predict every
premise's outage chance for a storm of that size; compare with who really had damage on their path.
Scored on Brier, log loss, AUC pooled and WITHIN each large storm (the weak spot of v0), and calibration.

Serving: config/assumptions.yaml -> risk.model chooses which rates go into nodes.csv `fail_prob`
(v0's values are kept in `fail_prob_v0`). Set it to v1 only if this backtest says v1 is better.
Writes data/processed/backtest_v1.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.sparse import csr_matrix
from sklearn.metrics import roc_auc_score

from _rates import fit_rates, fit_rates_v1, storm_exposure, zone_design

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
RISK = yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["risk"]
LARGE_STORM_MIN_RECORDS = 20
CAL_BINS = [0, 0.01, 0.05, 0.1, 0.2, 0.5, 0.8, 1.0001]
DAMPING_GRID = [1.0, 0.9, 0.8, 0.7, 0.6]


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


_require(OUT / "nodes.csv", OUT / "edges.csv", OUT / "damage_attributed.csv", OUT / "premise_event_labels.csv",
         OUT / "device_features.csv")
nodes = pd.read_csv(OUT / "nodes.csv", dtype={"node_id": str, "circuit_id": str})
edges = pd.read_csv(OUT / "edges.csv", dtype=str)
att = pd.read_csv(OUT / "damage_attributed.csv", dtype={"node_id": str})
labels = pd.read_csv(OUT / "premise_event_labels.csv", dtype=str)
X = zone_design(pd.read_csv(OUT / "device_features.csv", dtype={"device_id": str, "circuit_id": str}))
parent = dict(zip(edges.child_id, edges.parent_id))

# Premise x device incidence matrix (same as 05): row = premise, columns = devices on its upline path
premises = nodes.node_id[nodes.kind == "premise"].to_numpy()
devices = nodes.node_id[nodes.kind != "premise"].to_numpy()
dcol = {d: j for j, d in enumerate(devices)}
rows, cols = [], []
for i, p in enumerate(premises):
    cur = parent.get(p)
    while cur is not None:
        rows.append(i); cols.append(dcol[cur]); cur = parent.get(cur)
A = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(premises), len(devices)))
prow = {p: i for i, p in enumerate(premises)}

MODELS = {"v0": lambda rec, M: fit_rates(nodes, rec, M)[0],
          "v1": lambda rec, M: fit_rates_v1(nodes, rec, M, X)[0]}

# 1) Leave-one-storm-out: path hazard per premise for each model and held-out storm
sizes = att.groupby("event_id").size()
folds = {name: [] for name in MODELS}
ys = []
for ev in sizes.index:
    train = att[att.event_id != ev]
    med, M = storm_exposure(train.groupby("event_id").size())
    rec = train.groupby("node_id").size()
    m_ev = sizes[ev] / med
    y = np.zeros(len(premises))
    y[[prow[p] for p in labels.premise_id[labels.event_id == ev] if p in prow]] = 1
    ys.append(y)
    for name, fit in MODELS.items():
        hazard = A @ fit(rec, M).reindex(devices).fillna(0).to_numpy()
        folds[name].append((ev, m_ev, hazard))
Y = np.concatenate(ys)


def scores(name, damping):
    preds = [1 - np.exp(-(m ** damping) * h) for _, m, h in folds[name]]
    P = np.concatenate(preds)
    Pc = np.clip(P, 1e-9, 1 - 1e-9)
    big = {}
    for (ev, _, _), p, y in zip(folds[name], preds, ys):
        if sizes[ev] >= LARGE_STORM_MIN_RECORDS:
            big[ev] = {"records": int(sizes[ev]), "predicted_share_out": round(float(p.mean()), 4),
                       "actual_share_out": round(float(y.mean()), 4), "auc_within_storm": round(float(roc_auc_score(y, p)), 3)}
    return P, {"brier": round(float(np.mean((P - Y) ** 2)), 5),
               "log_loss": round(float(-np.mean(Y * np.log(Pc) + (1 - Y) * np.log(1 - Pc))), 5),
               "auc_pooled": round(float(roc_auc_score(Y, P)), 3), "large_storms": big}


damp = RISK["severity_damping"]
result = {"method": "leave-one-storm-out; both models re-fit without the held-out storm; oracle storm size",
          "severity_damping_used": damp, "brier_baseline_constant": round(float(np.mean((Y.mean() - Y) ** 2)), 5),
          "models": {}, "damping_grid": {}}
for name in MODELS:
    P, sc = scores(name, damp)
    cal = pd.DataFrame({"y": Y, "p": P, "bin": pd.cut(P, CAL_BINS, right=False)}).groupby("bin", observed=True).agg(
        n=("y", "size"), mean_predicted=("p", "mean"), actual_rate=("y", "mean")).round(4)
    result["models"][name] = {**sc, "calibration": [{"bin": str(b), **r} for b, r in cal.to_dict("index").items()]}
    result["damping_grid"][name] = {g: scores(name, g)[1]["brier"] for g in DAMPING_GRID}

# 2) Serve the chosen model: full-data fit -> nodes.csv fail_prob (v0 kept alongside for transparency)
chosen = RISK.get("model", "v0")
med, M = storm_exposure(sizes)
rec = att.groupby("node_id").size()
if "fail_prob_v0" not in nodes:
    nodes["fail_prob_v0"] = nodes["fail_prob"]
rates, fit = (fit_rates_v1(nodes, rec, M, X) if chosen == "v1" else fit_rates(nodes, rec, M))
nodes["fail_prob"] = (1 - np.exp(-nodes.node_id.map(rates))).fillna(0.0)
nodes.loc[nodes.kind == "premise", "fail_prob"] = 0.0
nodes.to_csv(OUT / "nodes.csv", index=False)
result["served_model"] = chosen
if chosen == "v1":
    result["v1_coefficients_per_sd"] = fit["v1_coefficients"]
(OUT / "backtest_v1.json").write_text(json.dumps(result, indent=1, default=str))

# 3) Report
print(f"premise-storm pairs={len(Y)}  constant-rate Brier baseline={result['brier_baseline_constant']}"
      f"  severity_damping={damp}")
for name, r in result["models"].items():
    print(f"\n== {name}: Brier={r['brier']}  log loss={r['log_loss']}  AUC pooled={r['auc_pooled']}")
    for ev, s in r["large_storms"].items():
        print(f"   {ev}: {s['records']:5d} records  predicted out {s['predicted_share_out']:.1%}  "
              f"actual {s['actual_share_out']:.1%}  AUC within storm {s['auc_within_storm']}")
    print("   Brier by severity_damping:", result["damping_grid"][name])
    print("   calibration:", [(c["bin"], round(c["mean_predicted"], 3), round(c["actual_rate"], 3)) for c in r["calibration"]])
print(f"\nserving: {chosen}  (set risk.model in config/assumptions.yaml)  -> {OUT / 'backtest_v1.json'}, nodes.csv")
