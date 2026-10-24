"""
HOUR 18-20 (Akshat): slide figures from the backtest and the storm planner -> docs/figures/*.png
  python pipelines/10_figures.py           (after 05 and 04; reads data/processed, runs the planner)
Aggregate numbers only (no IDs, coordinates or record-level values), so the PNGs are safe to commit.
Style: validated categorical palette (slots 1-3, checked with the dataviz validator: all-pairs CVD/normal-vision
pass; aqua is below 3:1 on the surface, so every series is direct-labelled), thin marks, recessive grid,
one y-axis per chart, text in ink colours (never the series colour).
"""
import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR, PROC = ROOT / "docs" / "figures", ROOT / "data" / "processed"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"     # categorical slots 1-3 (blue, orange, aqua)
PLAN_STORM_LABEL = "Feb 2025 storm"
CREW_SCENARIOS = [(20, S1), (40, S2), (60, S3)]   # crews of 3 people
CREW_SIZE = 3


def _require(*paths):
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        print(f"SKIP {Path(__file__).name}: missing {missing}")
        sys.exit(0)


_require(PROC / "backtest.json", PROC / "damage_work.csv", PROC / "nodes.csv")
OUT_DIR.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 11, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
    "axes.titlesize": 13, "axes.titlelocation": "left", "legend.frameon": False,
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT_DIR / name, dpi=200)
    plt.close(fig)
    print(f"  -> docs/figures/{name}")


# 1) Calibration: predicted vs actual outage rate (leave-one-storm-out)
bt = json.loads((PROC / "backtest.json").read_text())
cal = [c for c in bt["calibration"] if c["n"] >= 1000]          # drop tiny bins
x = [c["mean_predicted"] * 100 for c in cal]
y = [c["actual_rate"] * 100 for c in cal]
fig, ax = plt.subplots(figsize=(7, 5))
ax.plot([0, 100], [0, 100], color=INK2, lw=1, ls=(0, (4, 3)), zorder=1)
ax.text(70, 74, "perfect calibration", color=INK2, rotation=36, fontsize=9)
ax.plot(x, y, color=S1, lw=2, marker="o", ms=8, mec=SURFACE, mew=2, zorder=3)
# Label only the bins a judge will ask about (the low bins are crowded at the origin)
for xi, yi, c in zip(x, y, cal):
    if xi >= 30:
        ax.annotate(f"predicted {xi:.0f}% · actual {yi:.0f}%\n({c['n']:,} premise-storms)", (xi, yi),
                    textcoords="offset points",
                    xytext=(-10, -30) if xi > 80 else (-12, 10) if xi > 50 else (10, -26),
                    ha="right" if xi > 50 else "left", fontsize=8, color=INK2)
ax.set(xlim=(0, 100), ylim=(0, 100), xlabel="Predicted chance of losing power (%)",
       ylabel="Share that actually lost power (%)")
ax.set_title("Risk model on storms it never saw", pad=24)
ax.text(0, 1.025, f"Leave-one-storm-out backtest, {bt['premise_storm_pairs']:,} premise-storm pairs · "
        f"Brier {bt['brier']} vs {bt['brier_baseline_constant']} baseline", transform=ax.transAxes,
        fontsize=9, color=INK2)
save(fig, "1_calibration.png")

# 2) Held-out large storms: predicted vs actual share of customers out
big = sorted(bt["large_storms"], key=lambda s: s["records"])
meta = json.loads((PROC / "meta.json").read_text())
from datetime import date                                        # noqa: E402
labels = [date.fromisoformat(meta["events"][s["event_id"]]["start"]).strftime("%b %Y") for s in big]
fig, ax = plt.subplots(figsize=(7, 4.5))
w = 0.36
for k, (key, col, name) in enumerate([("predicted_share_out", S1, "Predicted"), ("actual_share_out", S2, "Actual")]):
    xs = [i + (k - 0.5) * (w + 0.03) for i in range(len(big))]
    vals = [s[key] * 100 for s in big]
    ax.bar(xs, vals, width=w, color=col, label=name, zorder=3)
    for xi, v in zip(xs, vals):
        ax.text(xi, v + 0.5, f"{v:.1f}%", ha="center", fontsize=9, color=INK)
ax.set_xticks(range(len(big)), [f"{l}\n({s['records']} damage records)" for l, s in zip(labels, big)])
ax.set_ylabel("Customers who lost power (%)")
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left")
ax.set_title("Each big storm predicted without seeing it", pad=12)
save(fig, "2_heldout_storms.png")

# 3) + 4) Storm planner: restoration curves and crews needed (Feb 2025 replay)
os.environ.pop("STORMHAVEN_DATA", None)
sys.path.insert(0, str(ROOT / "backend"))
from app.engines import planner                                  # noqa: E402
storm = next(s for s in planner.storms() if s["label"] == PLAN_STORM_LABEL)
plans = {c: planner.plan(storm["storm_id"], c, CREW_SIZE) for c, _ in CREW_SCENARIOS}
fig, ax = plt.subplots(figsize=(8, 4.8))
for c, col in CREW_SCENARIOS:
    p = plans[c]
    hrs = [pt["hour"] / 24 for pt in p["restore_curve"]]
    pct = [pt["pct_restored"] for pt in p["restore_curve"]]
    end = p["hours_to_restore"]["all"] / 24
    ninety = p["hours_to_restore"]["ninety_pct"] / 24
    ax.step(hrs, pct, where="post", color=col, lw=2, zorder=3,
            label=f"{c} crews ({c * CREW_SIZE} people): 90% back in {ninety:.1f} d, all in {end:.1f} d")
    ax.plot([hrs[-1]], [100], "o", ms=8, color=col, mec=SURFACE, mew=2, zorder=4)
    ax.annotate(f"{c} crews", (hrs[-1], 100), textcoords="offset points", xytext=(0, 9), ha="center",
                fontsize=9, color=INK)
ax.axhline(90, color=INK2, lw=0.8, ls=(0, (4, 3)), zorder=1)
ax.text(0.05, 91.5, "90% restored", fontsize=8, color=INK2)
ax.set(xlim=(0, None), ylim=(0, 110), yticks=range(0, 101, 20), xlabel="Days after the storm",
       ylabel="Customers restored (%)")
ax.legend(loc="lower right", fontsize=9)
ax.set_title(f"Replaying the {PLAN_STORM_LABEL}: {storm['damage_records']:,} repairs, "
             f"{plans[20]['customers_out']:,} customers out", pad=12)
save(fig, "3_restoration_curves.png")

p = plans[20]
fig, ax = plt.subplots(figsize=(7, 4.2))
tg = [t for t in p["targets"] if t["people_needed"]]
names = [{2: "2 days", 3: "3 days", 7: "1 week"}.get(t["days"], f"{t['days']} days") for t in tg]
vals = [t["people_needed"] for t in tg]
ax.barh(names, vals, color=S1, height=0.55, zorder=3)
for i, (t, v) in enumerate(zip(tg, vals)):
    ax.text(v + max(vals) * 0.02, i, f"{v} people ({t['crews_needed']} crews of {CREW_SIZE})", va="center",
            fontsize=10, color=INK)
ax.invert_yaxis()
ax.set_xlim(0, max(vals) * 1.55)
ax.set_xlabel("Line workers needed to restore every customer")
ax.grid(axis="y", visible=False)
ax.set_title(f"How many crews to restore everyone? ({PLAN_STORM_LABEL})", pad=24)
ax.text(0, 1.025, f"{p['total_person_hours']:,} person-hours of repair (AEP labor hours x 4.5)",
        transform=ax.transAxes, fontsize=9, color=INK2)
save(fig, "4_crews_needed.png")
print(f"-> {OUT_DIR}")
