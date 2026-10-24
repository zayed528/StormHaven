"""
HOUR 2-4 (Akshat): AEP labor workbook -> per-damage-type labor hours + indirect multiplier + access adders.
  python pipelines/04_load_labor.py

What the AEP workbook actually contains (see docs/DATA_NOTES.md):
  - labor hours per COMPATIBLE UNIT (CU: pole, crossarm, transformer, ...), install + removal, PERSON-hours.
    It does NOT list hours per damage type.
  - ONE indirect labor multiplier (drive + safety + setup), not separate travel / nonproductive values.
  - per-job labor adders (restricted access, remote location, ...).
So: hours per damage type = sum of CU hours over a repair recipe (config/assumptions.yaml ->
restoration.repair_recipes). The hours are AEP data; the recipes are our documented assumption.

Outputs (contract: backend/app/core/data_loader.py):
  cu_hours.csv        cu, install_hours, removal_hours, source_sheet
  labor_hours.csv     damage_type, hours, source
  multipliers.json    {"indirect_labor_multiplier": x}
  access_adders.json  {"limited": h, "blocked": h}
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
CFG = yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())["restoration"]

# ---- Names read from recon_report.md (AEP workbook Install_Labor_HackOHIO.xlsx) ----
LABOR_GLOB = "*Labor*.xlsx"
SHEET_CNC = "CNC"                                   # per-connector CU table + summary block
SHEET_CU = "Labor time material related"            # stacked blocks: "<X> CU Average Hours"
SHEET_ADDERS = "Labor only work"                    # columns: Original Intent, ..., INSTALL_HOURS
SHEET_ILM = "Indirect Labor Multiplier"             # A1 label, B1 value
COL_INSTALL, COL_REMOVE = "Avg Install Hours", "Avg Removal Hours"
COL_CNC_INSTALL, COL_CNC_REMOVE = "INSTALL_HOURS", "REMOVE_HOURS"
# Block title in SHEET_CU -> our CU key (keys match the "CU Group descriptions" sheet categories)
TITLE_TO_CU = {
    "Crossarm CU Average Hours": "ARM", "Bracket CU Average Hours": "BKT",
    "Pole CU Average Hours by Size": "POL", "Transformer CU Average Hours by Size": "XFMR",
    "Anchor CU Average Hours": "ANC", "Equipment Lead CU Average Hours": "EQL",
    "Grounding CU Average Hours": "GND", "Guying CU Average Hours": "GYF",
    "Dead-End CU Average Hours": "DEC", "Insulator CU Average Hours": "INS",
    "Pin CU Average Hours": "PIN", "Recloser CU Average Hours": "REC",
    "Secondary Conductor Attachment CU Average Hours": "SAA", "Service CU Average Hours": "SVC",
    "Switch CU Average Hours": "SWI", "Fuse Cutout Average Hours": "XCO",
}
# Our road_access level -> "Original Intent" row(s) in SHEET_ADDERS (summed). Mapping is an assumption.
ACCESS_ADDER_ROWS = {"limited": ["Access Constraint Adder"], "blocked": ["Remote Location Adder"]}
# ------------------------------------------------------------------------------------

found = sorted(f for f in RAW.glob(LABOR_GLOB) if not f.name.startswith("~$"))
if not found:
    print(f"SKIP 04_load_labor: no {LABOR_GLOB} in data/raw (backend keeps placeholder labor hours)")
    sys.exit(0)
BOOK = found[0]
sheets = pd.read_excel(BOOK, sheet_name=None, header=None)


def _num(v):
    """Cell -> float, or None for blanks/text (headers, notes)."""
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


# 1) Stacked "<X> CU Average Hours" blocks -> one row per CU key
def parse_cu_blocks(df: pd.DataFrame) -> list[dict]:
    """Scan down column A for known block titles; read header + numeric rows under each one."""
    rows, i = [], 0
    while i < len(df):
        title = str(df.iat[i, 0]).strip()
        if title not in TITLE_TO_CU:
            i += 1
            continue
        key, header = TITLE_TO_CU[title], [str(v).strip() for v in df.iloc[i + 1]]
        ci, cr = header.index(COL_INSTALL), header.index(COL_REMOVE)
        j, block = i + 2, []
        # Data rows continue until the install-hours cell is blank (the gap before the next block).
        while j < len(df) and _num(df.iat[j, ci]) is not None:
            block.append(df.iloc[j].tolist())
            j += 1
        if key == "POL":        # one CU per size group: POL_small / POL_medium / POL_large
            for r in block:
                rows.append({"cu": f"POL_{str(r[0]).strip().lower()}", "install_hours": _num(r[ci]),
                             "removal_hours": _num(r[cr]), "source_sheet": SHEET_CU})
        elif key == "XFMR":     # per kVA size + a CU-count-weighted average as "XFMR"
            cnt_i = header.index("CU Count")
            b = pd.DataFrame({"kva": [r[0] for r in block], "n": [_num(r[cnt_i]) for r in block],
                              "ins": [_num(r[ci]) for r in block], "rem": [_num(r[cr]) for r in block]})
            for r in b.itertuples():
                rows.append({"cu": f"XFMR_{int(r.kva)}", "install_hours": r.ins, "removal_hours": r.rem,
                             "source_sheet": SHEET_CU})
            rows.append({"cu": "XFMR", "install_hours": (b.ins * b.n).sum() / b.n.sum(),
                         "removal_hours": (b.rem * b.n).sum() / b.n.sum(), "source_sheet": SHEET_CU})
        else:
            r = block[0]
            rows.append({"cu": key, "install_hours": _num(r[ci]), "removal_hours": _num(r[cr]), "source_sheet": SHEET_CU})
        i = j      # continue scanning after this block
    return rows


# 2) Connectors: use the sheet's own summary block if present, else the mean of the per-CU table
def parse_connectors(df: pd.DataFrame) -> dict:
    """Find the 'Avg Install Hours' / 'Avg Removal Hours' header pair anywhere in the sheet."""
    for r in range(len(df)):
        for c in range(df.shape[1]):
            if str(df.iat[r, c]).strip() == COL_INSTALL and str(df.iat[r, c + 1]).strip() == COL_REMOVE:
                return {"cu": "CNC", "install_hours": _num(df.iat[r + 1, c]),
                        "removal_hours": _num(df.iat[r + 1, c + 1]), "source_sheet": SHEET_CNC}
    t = df.iloc[1:, :3].set_axis(["cu", "ins", "rem"], axis=1).dropna(subset=["ins"])
    return {"cu": "CNC", "install_hours": t.ins.astype(float).mean(),
            "removal_hours": t.rem.astype(float).mean(), "source_sheet": SHEET_CNC}


cu = pd.DataFrame(parse_cu_blocks(sheets[SHEET_CU]) + [parse_connectors(sheets[SHEET_CNC])])
missing_titles = set(TITLE_TO_CU) - {t for t in sheets[SHEET_CU][0].astype(str).str.strip()}
if missing_titles:
    print(f"WARNING: block titles not found in '{SHEET_CU}': {sorted(missing_titles)}")

# 3) Indirect labor multiplier: first numeric cell on a row whose label mentions "multip"
ilm = None
for row in sheets[SHEET_ILM].itertuples(index=False):
    if re.search("multip", str(row[0]), re.I):
        ilm = next((_num(v) for v in row[1:] if _num(v) is not None), None)
        if ilm:
            break
if ilm is None:
    sys.exit(f"ERROR: no numeric indirect labor multiplier found in sheet '{SHEET_ILM}'")

# 4) Access adders (person-hours added per job)
add = sheets[SHEET_ADDERS]
add = add.iloc[1:].set_axis([str(c).strip() for c in add.iloc[0]], axis=1)
by_intent = dict(zip(add["Original Intent"].astype(str).str.strip(), add["INSTALL_HOURS"].map(_num)))
adders = {lvl: float(sum(by_intent.get(n) or 0 for n in names)) for lvl, names in ACCESS_ADDER_ROWS.items()}

# 5) Damage-type hours from recipes
hours = cu.set_index("cu")
labor = []
for dtype, recipe in CFG["repair_recipes"].items():
    total = 0.0
    for key, qty, work in recipe:
        if key not in hours.index:
            sys.exit(f"ERROR: recipe '{dtype}' uses CU '{key}' not found in workbook. Known: {sorted(hours.index)}")
        h = hours.loc[key]
        total += qty * (h.install_hours + (h.removal_hours if work == "replace" else 0))
    labor.append({"damage_type": dtype, "hours": round(total, 3), "source": "AEP CU hours x assumed recipe"})
for dtype, h in CFG["non_cu_hours"].items():
    labor.append({"damage_type": dtype, "hours": float(h), "source": "assumed (no CU equivalent)"})

OUT.mkdir(parents=True, exist_ok=True)
cu.round(4).to_csv(OUT / "cu_hours.csv", index=False)
pd.DataFrame(labor).to_csv(OUT / "labor_hours.csv", index=False)
(OUT / "multipliers.json").write_text(json.dumps({"indirect_labor_multiplier": ilm}))
(OUT / "access_adders.json").write_text(json.dumps(adders))
print(f"{BOOK.name}: {len(cu)} CU rows, {len(labor)} damage types, indirect multiplier + {len(adders)} access adders")
print(pd.DataFrame(labor).to_string(index=False))
print(f"-> {OUT}/cu_hours.csv, labor_hours.csv, multipliers.json, access_adders.json")
