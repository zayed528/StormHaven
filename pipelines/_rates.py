"""
Shared estimator for per-device damage rates (used by 03_build_labels.py and 05_train_and_backtest.py,
so the backtest tests EXACTLY the model the app serves).   Owner: Akshat

Gamma-Poisson empirical Bayes, storms weighted by size:
  m_e   = records in storm e / median records per storm        (storm size in "typical storms")
  M     = sum of m_e                                           (total exposure)
  rate_i = (records_i + mu_k * beta_k) / (M + beta_k)          (damage rate per typical storm, device i of kind k)
  mu_k  = kind's mean records per device / M                    (prior mean)
  beta_k = prior strength in typical storms, from the kind's over-dispersion (method of moments):
           alpha_k = mean^2 / (var - mean),  beta_k = alpha_k / mu_k
  fail_prob_i = 1 - exp(-rate_i)                                (chance of >= 1 damage in a typical storm)
Kinds with no recorded damage borrow the transformer prior (closest analogue).
"""
import numpy as np
import pandas as pd

KINDS = ["transformer", "fuse", "recloser", "breaker", "step_transformer"]


def storm_exposure(records_per_event: pd.Series) -> tuple[float, float]:
    """(median records per storm, total exposure M in typical-storm units)."""
    med = float(records_per_event.median())
    return med, float((records_per_event / med).sum())


def fit_rates(nodes: pd.DataFrame, records_per_node: pd.Series, M: float) -> tuple[pd.Series, dict]:
    """Return (rate per node_id for every non-premise node, per-kind prior parameters)."""
    rates, fit = {}, {}
    for k in KINDS:
        ids = nodes.node_id[nodes.kind == k]
        n = records_per_node.reindex(ids).fillna(0).to_numpy(float)
        mean = n.mean() if len(n) else 0.0
        var = n.var(ddof=1) if len(n) > 1 else 0.0
        if mean == 0:                                   # never damaged: borrow the transformer prior
            base = fit["transformer"]
            mu, beta = base["mu"], base["beta"]
            fit[k] = {"mu": mu, "beta": beta, "devices": int(len(ids)), "records": 0, "borrowed_from": "transformer"}
        else:
            mu = mean / M
            alpha = mean ** 2 / (var - mean) if var > mean else np.inf
            beta = alpha / mu if np.isfinite(alpha) else 1e12      # no over-dispersion -> pool the kind fully
            fit[k] = {"mu": mu, "beta": beta, "devices": int(len(ids)), "records": int(n.sum())}
        rates.update(zip(ids, (n + mu * beta) / (M + beta)))
    return pd.Series(rates, dtype=float), fit
