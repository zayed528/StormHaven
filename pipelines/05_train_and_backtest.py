"""
HOUR 9-14 (Akshat): the credibility slide. Leave-one-storm-out backtest of the risk model the app serves.
  python pipelines/05_train_and_backtest.py
For every storm E: re-fit device damage rates WITHOUT E (same estimator as 03, pipelines/_rates.py), predict each
premise's outage chance for a storm of E's actual size, and compare with which premises really had damage on
their upline path in E (premise_event_labels.csv).
Severity is set to E's real size ("oracle severity"): this tests the network/history model, not storm forecasting.

Writes data/processed/backtest.json:
  brier, auc (pooled + per large storm), calibration table, per-storm predicted vs actual share of premises out,
  restoration duration summary (coverage NOT computed: see note).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.sparse import csr_matrix
from sklearn.metrics import roc_auc_score

from _rates import fit_rates, storm_exposure      # identical math to 03_build_labels.py

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
LARGE_STORM_MIN_RECORDS = 20                        # storms reported individually in the summary
CAL_BINS = [0, 0.01, 0.05, 0.1, 0.2, 0.5, 0.8, 1.0001]
DAMPING = yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["risk"]["severity_damping"]
DAMPING_GRID = [1.0, 0.9, 0.8, 0.7, 0.6]           # reported so the team can re-tune severity_damping


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


_require(OUT / "premise_event_labels.csv", OUT / "damage_attributed.csv", OUT / "nodes.csv", OUT / "edges.csv")
nodes = pd.read_csv(OUT / "nodes.csv", dtype={"node_id": str, "circuit_id": str})
edges = pd.read_csv(OUT / "edges.csv", dtype=str)
att = pd.read_csv(OUT / "damage_attributed.csv", dtype={"node_id": str})
labels = pd.read_csv(OUT / "premise_event_labels.csv", dtype=str)
parent = dict(zip(edges.child_id, edges.parent_id))

# Premise x device incidence matrix: row = premise, columns = every device on its upline path.
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

sizes = att.groupby("event_id").size()
folds = []                                                       # (event, size in typical storms, path hazard, y)
for ev in sizes.index:
    train = att[att.event_id != ev]
    med, M = storm_exposure(train.groupby("event_id").size())
    rates, _ = fit_rates(nodes, train.groupby("node_id").size(), M)
    m_ev = sizes[ev] / med                                       # held-out storm's size in typical storms
    hazard = A @ rates.reindex(devices).fillna(0).to_numpy()     # summed rates along each premise's path
    y = np.zeros(len(premises))
    y[[prow[p] for p in labels.premise_id[labels.event_id == ev] if p in prow]] = 1
    folds.append((ev, m_ev, hazard, y))


def predict(m, hazard, damping):
    """Same formula the app serves: P(out) = 1 - exp(-m^damping * path hazard)."""
    return 1 - np.exp(-(m ** damping) * hazard)


grid = []
for g in DAMPING_GRID:
    pp = np.concatenate([predict(m, h, g) for _, m, h, _ in folds]); yy = np.concatenate([f[3] for f in folds])
    pc = np.clip(pp, 1e-9, 1 - 1e-9)
    grid.append({"severity_damping": g, "brier": round(float(np.mean((pp - yy) ** 2)), 5),
                 "log_loss": round(float(-np.mean(yy * np.log(pc) + (1 - yy) * np.log(1 - pc))), 5)})

y_all, p_all, per_storm = [], [], []
for ev, m_ev, hazard, y in folds:
    pred = predict(m_ev, hazard, DAMPING)
    y_all.append(y); p_all.append(pred)
    per_storm.append({"event_id": ev, "records": int(sizes[ev]), "size_vs_typical": round(float(m_ev), 1),
                      "predicted_share_out": round(float(pred.mean()), 4), "actual_share_out": round(float(y.mean()), 4),
                      "auc": round(float(roc_auc_score(y, pred)), 3) if 0 < y.sum() < len(y) else None})

Y, Pr = np.concatenate(y_all), np.concatenate(p_all)
bins = pd.cut(Pr, CAL_BINS, right=False)
cal = pd.DataFrame({"y": Y, "p": Pr, "bin": bins}).groupby("bin", observed=True).agg(
    n=("y", "size"), mean_predicted=("p", "mean"), actual_rate=("y", "mean")).round(4)

dur = pd.read_csv(OUT / "durations.csv") if (OUT / "durations.csv").exists() else pd.DataFrame(columns=["event_id", "hours"])
dur_by_storm = {ev: dur[dur.event_id == ev].hours.quantile([0.1, 0.5, 0.9]).round(1).tolist()
                for ev in sizes[sizes >= LARGE_STORM_MIN_RECORDS].index}

res = {
    "method": "leave-one-storm-out; device rates re-fit without the held-out storm; oracle storm size",
    "severity_damping_used": DAMPING,
    "severity_damping_grid": grid,
    "premise_storm_pairs": int(len(Y)),
    "brier": round(float(np.mean((Pr - Y) ** 2)), 5),
    "brier_baseline_constant": round(float(np.mean((Y.mean() - Y) ** 2)), 5),
    "auc_pooled": round(float(roc_auc_score(Y, Pr)), 3),
    "calibration": [{"bin": str(b), **r} for b, r in cal.to_dict("index").items()],
    "large_storms": [s for s in per_storm if s["records"] >= LARGE_STORM_MIN_RECORDS],
    "all_storms": per_storm,
    "repair_hours_p10_p50_p90_by_large_storm": dur_by_storm,
    "restoration_p10_p90_coverage": None,
    "restoration_note": ("Not computed. ARCOS repair dates are whole days and look like record-closure dates "
                         "(median 21-23 days for two storms, 1 day for another); confirm what Repaired_D means "
                         "with AEP before using it to score restoration ranges."),
}
(OUT / "backtest.json").write_text(json.dumps(res, indent=1, default=str))
print("severity_damping grid:", grid)
print(f"pairs={res['premise_storm_pairs']}  Brier={res['brier']} (constant-rate baseline {res['brier_baseline_constant']})"
      f"  AUC={res['auc_pooled']}")
print("large storms (held out):")
for s in res["large_storms"]:
    print(f"  {s['event_id']}: {s['records']} records (~{s['size_vs_typical']}x typical)  predicted out "
          f"{s['predicted_share_out']:.1%}  actual {s['actual_share_out']:.1%}  AUC {s['auc']}")
print("calibration (predicted -> actual):")
print(cal.to_string())
print(f"-> {OUT / 'backtest.json'}")
