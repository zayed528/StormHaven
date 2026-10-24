# StormHaven data notes

**Owner:** Jaid. This covers what each AEP file contains, how the files join, what's missing, and how each pipeline handles it. The source is `make recon` (→ `data/processed/recon_report.md`) plus the profiling done when pipelines 02–06 were written.
**Rule:** AEP files live in `data/raw/` and outputs in `data/processed/`; both are git-ignored. Describe structure and aggregate counts here. Never put premise IDs, coordinates, addresses or record-level values in committed files.

## Getting the data

The package is in the organizers' repo `hackohio/aep_challenge_hack26` under `data/` (three zips plus the labor workbook) and `docs/structure_drawings.pdf`. Unzip all three into `data/raw/` with the files flat (no subfolders), keeping each shapefile's companion files together, and copy the workbook and PDF there too. Then run `make pipelines`. Never commit any of it.

## Inventory (all received)

| file (in `data/raw/`) | geometry / format | rows | used by | notes |
|---|---|---|---|---|
| `matched_upstream.txt` | TXT | 117,599 | **02** | the topology (see below) |
| `Customer_Clip` | points, EPSG:4326 | 117,642 | **not used** | contains street addresses, road names, city, and a `critical_c` column with **"LS Life Support"** flags. Deliberately never read. |
| `Transformer_Clip` | points | ~27k | 02, 03, 06 | `id` joins the topology (25,300 / 25,302) |
| `Fuse_Bank_Clip` | points | ~7.6k | 02, 03 | `id` joins ~98.5%; a few more via `location_n` |
| `Recloser_Bank_Clip` | points | 331 | 02, 03 | joins on `location_n` (= the topology's `<code>`), **not** `id` |
| `Switch_Clip` | points | 900 | — | not in the topology (switches aren't protective devices) |
| `Pole_Clip` | points | ~107k | — | not needed; pole damage is located by ARCOS coordinates |
| `Primary_ExportFeatures` | lines | ~63k | 06 | merged per `circuit_id` → `circuits.geojson` (map) |
| `Secondary_ExportFeatures` | lines | ~127k | — | skipped: too heavy for the map, adds nothing at map zoom |
| `arcos_prod_damage_09_28_Clip` | points | 1,659 | **03** | damage records (see below) |
| `Hospitals_Medic…`, `Fire_Stations…`, `Ambulance_Servi…` | points, **Web Mercator + NAVD88 (compound CRS)** | 5 / 37 / 10 | 06 | reprojected to 2D; only matched transformer IDs leave the pipeline |
| `Install_Labor_HackOHIO.xlsx` | Excel | — | 04 | labor workbook (section below) |
| `structure_drawings.pdf` | PDF | — | manual | for checking repair recipes (TODO, Akshat) |

Every shapefile has its .shp/.shx/.dbf/.prj (checked by `01_recon.py`).

## Topology: `matched_upstream.txt` → `02_build_topology.py`

- Tab-separated, **no header**, one line per premise: `<premise_id>\t<class>*<id>*<type>*<code>\t…`
- Ordered **nearest first**. Every line starts with a distribution transformer and ends with a circuit breaker. In between: fuses, hydraulic/electronic reclosers, step transformers, one sectionalizer. Chains are 2–13 elements long.
- Premise IDs are 9-digit numbers and equal `Customer_Clip.premise_nu`.
- The breaker's `<code>` (e.g. `0000027`) **is the `circuit_id`** used across all GIS layers. All 110 match.
- Nearly a tree: **60 of ~150k nodes have two candidate parents**. 02 keeps the parent seen on the most premise chains, then checks for cycles and that every node reaches a breaker.
- Node IDs in our outputs: `XF-` transformer, `ST-` step transformer, `FU-` fuse, `RC-` recloser, `SC-` sectionalizer, `CB-` breaker, plus the 9-digit premise IDs. `core/privacy.py` scrubs all of these formats.
- Coordinates: breakers, step transformers, the sectionalizer, 91 fuses and 1 recloser have no point in any shapefile, so lat/lon is empty. They aren't drawn and don't need it.
- **Privacy:** each premise is placed at its transformer. No home-level coordinate exists anywhere in `data/processed`.

## ARCOS damage: `arcos_prod_damage_09_28_Clip` → `03_build_labels.py`

Columns: `Outage_Num, Incident_W, Event, Region, District, Crew_Area, Substation, Circuit, Report_Tim, Reporting_, Reporting1, TASK_Crew, TASK_Job_I, Status, Repaired, Repaired_D, Repaired_B, Asset_Type, Inform_Wor, Media, Access_Iss, Special_Eq, Longitude, Latitude, NEAR_FID, NEAR_DIST`.

| finding | consequence / how 03 handles it |
|---|---|
| `Event` = "Default" on every row; `Outage_Num`/`Incident_W` = 0 | **No storm IDs.** Storms = runs of report days with gaps ≤ `risk.event_gap_days` (1) → **36 storms**. Only 3 have ≥ 20 records (Feb 2025: 1,244 records; Sep 2024: 193; Jan 2025: 46). Most are 1–5 records. |
| `Circuit`/`Substation` are anonymized names (`CIR60`, `STATION2`) that **don't match** GIS `circuit_id` | Spatial matching instead. Points sit on GIS features (`NEAR_DIST` ≈ 0). |
| No device-ID column | Spatial attribution: Fuse Bank / Recloser Bank / Transformer → nearest device of that type (median 0 m). Secondary wire → nearest transformer. Primary wire / pole / switch → nearest transformer's **first upstream protective device** (the device that would open). **100% of usable records attributed.** |
| Damage type = `Inform_Wor` × `Asset_Type` (clean 1:1 combos) | mapped in 03 `DAMAGE_NAME_MAP` → `broken_pole, wire_down, fuse_cutout_damaged, recloser_damaged, switch_damaged, transformer_failed` |
| Light (5) and Capacitor Bank (6) records | dropped as non-interrupting (team decision) |
| `Report_Tim` / `Repaired_D` are **whole days** (no times) | durations are day-resolution only |
| Repair durations look administrative: median 21–23 days in two storms, 1 day in Feb 2025; 76 unrepaired records carry placeholder future dates | `durations.csv` keeps repaired records only; **restoration backtesting is on hold** until AEP confirms what `Repaired_D` means |
| No quantity column; `Media` holds small integers 0–6 | meaning unknown, not used (ask a mentor) |
| `Access_Iss` (Yes on ~1/3 of records) and `Special_Eq` | not used yet; could calibrate the road-access scenario (Akshat) |
| `District`, `Crew_Area`, `TASK_*`, `Status`, `Repaired_B` are empty | ignored |

Outputs: `nodes.csv` (adds `fail_prob` and `n_events_observed`), `damage_mix.json`, `meta.json` (storm sizes, severity curve, damage shares, per-kind priors), `premise_event_labels.csv` (**positives only**), `damage_attributed.csv`, `durations.csv`. The method is explained in `docs/ASSUMPTIONS.md`.

## Priority facilities → `06_export_map_layers.py`

The 52 facilities are reprojected from the compound CRS and matched to the nearest transformer within 500 m: **41 matched** (4/5 hospitals, 30/37 fire, 7/10 ambulance). Only the transformer IDs are written (`priority_nodes.csv`); names, addresses and coordinates are dropped inside the script. They raise restoration priority and are never shown.

## Labor workbook: `Install_Labor_HackOHIO.xlsx` → `04_load_labor.py`

Five sheets. **It is not a per-damage-type table.** It has hours per compatible unit (CU), one indirect multiplier, and per-job adders.

| sheet | layout | use |
|---|---|---|
| `CNC` | per-connector table + a summary block (E1:G3) | CU key `CNC` |
| `Labor time material related` | **stacked blocks** titled "`<X>` CU Average Hours", each with its own header row | `ARM, BKT, POL_small/medium/large, XFMR_<kVA>, XFMR` (count-weighted), `ANC, EQL, GND, GYF, DEC, INS, PIN, REC, SAA, SVC, SWI, XCO` |
| `Labor only work` | `Original Intent`, `Anonymized Work Type`, `Anonymized Labor Description`, `INSTALL_HOURS`; last 4 rows shifted one column | access adders: limited → "Access Constraint Adder", blocked → "Remote Location Adder" |
| `Indirect Labor Multiplier` | A1 label, B1 value | one multiplier for drive + safety + setup |
| `CU Group descriptions` | code meanings | naming only |

Hours per damage type = Σ CU hours over a repair recipe (`assumptions.yaml`). The hours are AEP's; the recipes are our assumption.

## Join keys (verified)

| from | to | key | match |
|---|---|---|---|
| topology premise | `Customer_Clip.premise_nu` | 9-digit premise ID | 117,595 / 117,599 (not used: we don't read the customer file) |
| topology transformer | `Transformer_Clip.id` | `<id>` | 25,300 / 25,302 |
| topology fuse | `Fuse_Bank_Clip.id`, then `.location_n` | `<id>`, then `<code>` | 6,666 / 6,757 |
| topology recloser | `Recloser_Bank_Clip.location_n` | `<code>` | 322 / 323 |
| topology breaker `<code>` | `circuit_id` in Customer / Transformer / Primary | circuit code | 110 / 110 |
| ARCOS | graph nodes | spatial (EPSG:3857 metres) | 100% of usable records |
| ARCOS `Circuit` | GIS `circuit_id` | — | **no match** (anonymized differently) |
