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


# ---------------------------------------------------------------- model v1: features set the prior
V1_KINDS = ["fuse", "recloser", "breaker"]          # protective zones; transformers stay on the v0 kind prior


def zone_design(features: pd.DataFrame) -> pd.DataFrame:
    """Model inputs per protective zone (from 08_features.py). Exposure only: nothing learned from damage.
    Pole age and wood share were tested and carried no signal, so they're left out."""
    f = features.set_index("device_id")
    X = pd.DataFrame(index=f.index)
    X["log_poles"] = np.log1p(f.n_poles)
    X["log_transformers"] = np.log1p(f.n_transformers)
    X["log_overhead_km"] = np.log1p(f.line_km_overhead)
    X["underground_share"] = f.underground_share.fillna(0.0)     # no line assigned -> treat as overhead-only
    X["has_line"] = (f.line_km > 0).astype(float)
    X["is_recloser"] = (f.kind == "recloser").astype(float)
    X["is_breaker"] = (f.kind == "breaker").astype(float)
    return X


def fit_rates_v1(nodes: pd.DataFrame, records_per_node: pd.Series, M: float,
                 X: pd.DataFrame, alpha_reg: float = 1e-3) -> tuple[pd.Series, dict]:
    """Like fit_rates, but for fuses/reclosers/breakers the prior mean comes from a Poisson regression on zone
    features instead of one number per kind:  E[records_i] = M * mu_i,  mu_i = exp(X_i . b).
    Shrinkage strength per kind is re-estimated around those means (method of moments on the residuals):
      alpha_k = sum (M mu_i)^2 / sum ((N_i - M mu_i)^2 - N_i)      rate_i = (N_i + alpha_k) / (M + alpha_k / mu_i)
    Everything else (transformers, step transformers) is exactly v0."""
    from sklearn.linear_model import PoissonRegressor

    rates, fit = fit_rates(nodes, records_per_node, M)        # v0 for every kind; v1 overrides protective zones
    protective = set(nodes.node_id[nodes.kind.isin(V1_KINDS)])          # build once, not per row
    ids = [i for i in X.index if i in protective]
    Xz = X.loc[ids]
    mean, std = Xz.mean(), Xz.std().replace(0, 1.0)
    Xs = (Xz - mean) / std
    n = records_per_node.reindex(ids).fillna(0).to_numpy(float)
    glm = PoissonRegressor(alpha=alpha_reg, max_iter=3000).fit(Xs, n)
    mu = glm.predict(Xs) / M                                  # prior rate per typical storm
    kind = nodes.set_index("node_id").kind.reindex(ids).to_numpy()
    for k in V1_KINDS:
        sel = kind == k
        Nk, Ek = n[sel], M * mu[sel]
        denom = float(((Nk - Ek) ** 2 - Nk).sum())
        alpha = float((Ek ** 2).sum() / denom) if denom > 0 else 1e12
        r = (Nk + alpha) / (M + alpha / mu[sel])
        rates.loc[np.array(ids)[sel]] = r
        fit[k] = {**fit[k], "model": "v1", "alpha": alpha}
    fit["v1_coefficients"] = {c: round(float(b), 4) for c, b in zip(X.columns, glm.coef_)}   # per 1 SD of each input
    return rates, fit
