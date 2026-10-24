"""
HOUR 9-14 (Akshat): the slide that wins credibility.
 A) Risk calibration: does "30%" happen ~30% of the time? (leave-one-event-out)
 B) Restoration coverage: how often does our P10-P90 contain the actual duration?
Writes data/processed/backtest.json  (TODO: calibration plot for the slides)
STATUS: needs premise_event_labels.csv from 03, which needs ARCOS + topology (not received yet).
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import calibration_curve

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"


def _require(*paths):
    """Exit cleanly (so `make pipelines` keeps going) when an input isn't there yet."""
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing} (backend keeps using the synthetic fallback)")
        sys.exit(0)


_require(OUT / "premise_event_labels.csv")
labels = pd.read_csv(OUT / "premise_event_labels.csv")
events = labels.event_id.unique()

# ---- A) Leave-one-event-out: predict each event from the others' history ----
preds = []
# Hold out one storm at a time, so a storm never helps predict itself (no leakage).
for ev in events:
    train, test = labels[labels.event_id != ev], labels[labels.event_id == ev]
    # Feature: how often this premise lost power in the OTHER storms. New premises get the overall rate.
    hist = train.groupby("premise_id").out.mean().rename("hist_rate")
    t = test.join(hist, on="premise_id").fillna({"hist_rate": train.out.mean()})
    # Feature set v1 — extend with path length, asset mix, distance to substation, event severity
    X_tr = train.join(hist, on="premise_id")[["hist_rate"]]
    model = LogisticRegression().fit(X_tr, train.out)
    t["p"] = model.predict_proba(t[["hist_rate"]])[:, 1]
    preds.append(t)
P = pd.concat(preds)
# Calibration: in each bin, predicted probability vs. the share that actually went out (ideal: equal).
frac_pos, mean_pred = calibration_curve(P.out, P.p, n_bins=8, strategy="quantile")
# Brier score: mean squared error of probabilities (0 = perfect; lower is better).
brier = float(np.mean((P.p - P.out) ** 2))

# ---- B) Restoration interval coverage (fill in once engine is wired to historical scenarios) ----
# For each historical outage: run estimate_restoration with that event's damage -> check p10 <= actual <= p90
# Target: about 80% of actual durations fall inside P10-P90 (that's what an 80% interval promises).
coverage = None   # TODO

res = {"brier": brier, "calibration": list(zip(mean_pred.round(3).tolist(), frac_pos.round(3).tolist())),
       "restoration_p10_p90_coverage": coverage}
(OUT / "backtest.json").write_text(json.dumps(res, indent=1))
print(res)
