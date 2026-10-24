"""
HOUR 1-3 (Jaid): inventory every file AEP gave us. Run FIRST.
  make recon     (or: python pipelines/01_recon.py)
Writes data/processed/recon_report.md: file inventory, shapefile sidecar check, CRS, row counts,
columns, sample rows, and columns that look like shared IDs across files (our join keys).
Read-only on data/raw. The report contains AEP samples: it lives in data/processed (git-ignored).
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
# A shapefile is really 4+ files; without .shx/.dbf it won't open, and without .prj the CRS is unknown.
SIDECARS = [".shp", ".shx", ".dbf", ".prj"]

# Skip placeholders and Excel lock files ("~$name.xlsx", created while a workbook is open).
files = [f for f in sorted(RAW.rglob("*")) if f.is_file() and f.name != ".gitkeep" and not f.name.startswith("~$")]
cols_by_file = {}
lines = ["# Data recon report\n", "## Inventory", "| file | size | type |", "|---|---|---|"]
lines += [f"| {f.relative_to(RAW)} | {f.stat().st_size / 1024:,.0f} KB | {f.suffix.lower() or '?'} |" for f in files]
if not files:
    lines.append("| (data/raw is empty; backend runs on the synthetic network) | | |")

shps = [f for f in files if f.suffix.lower() == ".shp"]
if shps:
    lines += ["\n## Shapefile sidecars", "| shapefile | " + " | ".join(SIDECARS) + " |", "|---|" + "---|" * len(SIDECARS)]
    for f in shps:
        lines.append(f"| {f.stem} | " + " | ".join("yes" if f.with_suffix(s).exists() or f.with_suffix(s.upper()).exists()
                                                    else "**MISSING**" for s in SIDECARS) + " |")
lines.append("")

for f in files:
    suf = f.suffix.lower()
    try:
        if suf == ".shp":
            import geopandas as gpd
            g = gpd.read_file(f)
            cols_by_file[f.name] = set(g.columns)
            lines += [f"## {f.name}", f"- rows: {len(g)}  CRS: {g.crs}  geometry: {g.geom_type.value_counts().to_dict()}",
                      f"- columns: {list(g.columns)}", "```", g.drop(columns="geometry").head(5).to_string(), "```\n"]
        elif suf in {".xlsx", ".xls"}:
            # header=None: AEP sheets can be stacked blocks, not tidy tables; show the raw grid.
            for sheet, df in pd.read_excel(f, sheet_name=None, header=None).items():
                header = [str(c) for c in df.iloc[0].dropna()] if len(df) else []
                cols_by_file[f"{f.name}:{sheet}"] = set(header)
                lines += [f"## {f.name} / {sheet}", f"- shape: {df.shape}  (read with header=None; first row shown as row 0)",
                          f"- first-row values: {header}", "```", df.head(12).to_string(), "```\n"]
        elif suf in {".txt", ".csv"}:
            head = f.read_text(errors="ignore").splitlines()[:8]
            lines += [f"## {f.name}", "First lines (check delimiter + header):", "```", *head, "```\n"]
        elif suf == ".pdf":
            lines += [f"## {f.name}", "- PDF (structure diagrams?): read manually.\n"]
    except Exception as e:  # keep going: one bad file shouldn't hide the rest
        lines += [f"## {f.name}", f"- **could not read**: {e!r}\n"]

# Candidate join keys: column names (case-insensitive) appearing in 2+ files
seen = {}
for name, cols in cols_by_file.items():
    for c in cols:
        seen.setdefault(c.lower(), []).append(name)
shared = {c: fs for c, fs in seen.items() if len(fs) > 1 and c != "geometry"}
lines += ["## Candidate join keys", *([f"- `{c}`: {fs}" for c, fs in shared.items()] or ["- none found"])]
(OUT / "recon_report.md").write_text("\n".join(lines))
print(f"{len(files)} raw files, {len(shps)} shapefiles, {len(shared)} candidate join keys")
print(f"Full report -> {OUT / 'recon_report.md'}")
