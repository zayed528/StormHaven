# StormHaven data notes

**Owner:** Jaid. This file covers what each AEP file contains, how the files join, and what's missing. It is filled from `make recon`, which writes `data/processed/recon_report.md`.
**Rule:** AEP files live in `data/raw/` and processed outputs in `data/processed/`. Both are git-ignored. Never copy AEP values into committed files: describe structure here, not numbers.

## Status at setup (hour 0)

| AEP source (per challenge brief) | expected format | received? | file in `data/raw/` | pipeline |
|---|---|---|---|---|
| ARCOS damage assessment | shapefile | **no** | — | 03 |
| Circuit GIS extracts (circuits, protective devices, relationships) | shapefile | **no** | — | 02, 06 |
| Upline flow / topology | TXT | **no** | — | 02 |
| STORMS labor-hour reference | Excel | **yes** (combined workbook) | `Install_Labor_HackOHIO.xlsx` | 04 ✅ runs |
| Indirect labor assumptions | Excel | **yes**, inside the same workbook | same file | 04 ✅ runs |
| Priority locations (hospitals, fire, EMS) | shapefile | **no** | — | 06 |
| Structure diagrams | PDF | **no** | — | manual (validates repair recipes) |

Until the shapefiles and TXT arrive, the backend runs on the **synthetic network** with **real AEP labor hours** (`/api/health` shows `synthetic_data: true, labor_from_aep: true`). No shapefiles were present, so the sidecar check (.shp/.shx/.dbf/.prj) has nothing to report yet. `01_recon.py` checks it automatically when they arrive.

## `Install_Labor_HackOHIO.xlsx` (received)

One workbook with five sheets. **It does not match what the starter pipeline assumed**: there is no per-damage-type labor table and no separate travel or nonproductive multipliers. What it has:

| sheet | layout | what it is | how we use it |
|---|---|---|---|
| `CNC` | Table: `CD_CU`, `INSTALL_HOURS`, `REMOVE_HOURS`, one row per connector CU (~95 rows). A summary block at E1:G3 has `CU Count`, `Avg Install Hours`, `Avg Removal Hours`. | labor per connector compatible unit | the summary averages become CU key `CNC` |
| `Labor time material related` | **Stacked blocks**, not one table. Each block is a title row (`"<X> CU Average Hours"`), a header row (`Avg Install Hours`, `Avg Removal Hours`, sometimes `CU Count`, `Size Group`, `Height Range`, `Size (kVA)`), then data rows. Blank rows separate the blocks. | average install/removal hours per CU group: crossarm, bracket, pole (by size group), transformer (by kVA), anchor, equipment lead, grounding, guying, dead-end, insulator, pin, recloser, secondary attachment, service, switch, fuse cutout | parsed into `cu_hours.csv` with keys `ARM, BKT, POL_small/medium/large, XFMR_<kVA>, XFMR` (CU-count-weighted average), `ANC, EQL, GND, GYF, DEC, INS, PIN, REC, SAA, SVC, SWI, XCO` |
| `Labor only work` | Header: `Original Intent`, `Anonymized Work Type`, `Anonymized Labor Description`, `INSTALL_HOURS`. **The last 4 rows are shifted**: the description sits in the *Work Type* column. Two rows are "per cubic foot". | per-job adders (restricted access, backyard, remote, hand dig, rock hole, ...) | `Access Constraint Adder` → road access *limited*; `Remote Location Adder` → *blocked* (our mapping) → `access_adders.json` |
| `Indirect Labor Multiplier` | A1 = label, B1 = value, A2 = note | **one** multiplier for drive time, safety discussion and setup, applied to all labor hours | `multipliers.json` → `{"indirect_labor_multiplier": x}` |
| `CU Group descriptions` | `Category`, `Suggested Anonymous Description` | meaning of the CU codes (ARM, BKT, POL, ...). `DEG` and `XRA` have no hours block. | naming only |

**Consequences (already handled):**
- Hours per damage type = Σ CU hours over a **repair recipe** in `config/assumptions.yaml` (`restoration.repair_recipes`). The recipes are our assumption; the hours are AEP's. `tree_on_line` has no CU, so its hours are assumed (`non_cu_hours`).
- Labor hours are treated as **person-hours**: clock time = hours × indirect multiplier ÷ `crew_size_persons`. **Open question for AEP mentors:** are CU hours per person or per crew?
- The data-loader contract accepts the new `multipliers.json` shape, and still accepts the old `{travel, nonproductive}` shape in case AEP sends a separate indirect-labor file later.
- `04_load_labor.py` finds the workbook by glob (`*Labor*.xlsx`), sheet names and block titles. If AEP sends a revised workbook, update the names block at the top of `04` and re-run.

## Expected files (not received). Fill this in from `recon_report.md`.

For each file: CRS, row count, columns, ID format, and gaps. Then update the TODO blocks in pipelines 02, 03 and 06. **Do not guess column names: copy them from the recon report.**

### Upline flow / topology (TXT) → `02_build_topology.py`
- [ ] delimiter, header?
- [ ] layout: one row per (premise, upline device, sequence)? or parent → child pairs? (02 handles both: set `COLS["order"] = None` for pairs)
- [ ] ID formats for premise and equipment. **Send them to Nandan** so `core/privacy._INTERNAL_ID` can scrub them.
- [ ] do any nodes have more than one parent (loops, ties)? 02 prints a warning and keeps the first
- [ ] premise coordinates present? If not, place each premise at its transformer's (masked) coordinate (TODO in 02)

### Circuit GIS extracts (shapefiles) → `02`, `06`
- [ ] which file has protective devices; device type values → `KIND_MAP` in 02
- [ ] circuit ID column name; does it match ARCOS and the upline file?
- [ ] CRS (reprojected to EPSG:4326 in 06)

### ARCOS damage assessment (shapefile) → `03_build_labels.py`
- [ ] event ID, circuit, damage type, quantity, report time, repair time column names → `A` dict in 03
- [ ] **is there an equipment/device column?** If yes, set `A["equipment"]`. If not, 03 matches each record to the nearest device on the same circuit (masked coordinates, so this is approximate). Record the match rate here.
- [ ] damage-type values → `DAMAGE_NAME_MAP` in 03, mapping onto our keys (`broken_pole`, `broken_crossarm`, `wire_down`, `transformer_failed`, `fuse_blown`, `recloser_damaged`, `tree_on_line`). Unmapped types fall back to `unknown_damage_type_hours`.
- [ ] number of events, and records per event (Akshat uses this for the severity percentile)
- [ ] are repair timestamps usable for duration backtesting? (03 writes `durations.csv`)

### Priority locations (shapefile) → `06_export_map_layers.py`
- [ ] facility type column; CRS
- [ ] match rate to the nearest transformer or fuse within 500 m
- **Privacy:** only `priority_nodes.csv` (device IDs) leaves the pipeline. Facility coordinates never reach the API or the map.

## Join keys

`01_recon.py` lists column names shared by two or more files under "Candidate join keys". Expected joins:

| from | to | key | notes |
|---|---|---|---|
| upline TXT (premise → device) | GIS devices | device ID | TODO |
| ARCOS damage | GIS devices | device ID if present, else circuit + nearest | TODO |
| ARCOS damage type | `labor_hours.csv` | `DAMAGE_NAME_MAP` → recipe key | TODO |
| priority locations | devices | spatial nearest (500 m) | TODO |
