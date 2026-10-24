# StormHaven data notes

**Owner:** Jaid. This covers what each AEP file contains, how the files join, what's missing, and how each pipeline handles it. The source is `make recon` (→ `data/processed/recon_report.md`) plus the profiling done when pipelines 02–06 were written.
**Rule:** the AEP data is committed **only** as compressed archives in `data/archives/` (team decision; the repo is private). `data/raw/` and `data/processed/` are generated and git-ignored. In docs and code, describe structure and aggregate counts; never paste premise IDs, coordinates, addresses or record-level values.

## Getting the data

`git pull`, then `make data`. That unpacks `data/archives/` into `data/raw/` (and the weather cache into `data/processed/weather_cache/`) and runs pipelines 01–07, in about 15 seconds. Without `make`, run `python pipelines/00_unpack_data.py` and then the pipelines in order.

| archive (`data/archives/`) | contents |
|---|---|
| `aep_gis_shapefiles.zip` | 11 shapefile layers (all companion files): transformers, fuses, reclosers, switches, poles, primary + secondary lines, ARCOS damage, hospitals, fire, ambulance. **`Customer_Clip` is excluded**: it holds street addresses and life-support flags, and no code uses it. |
| `aep_topology.zip` | `matched_upstream.txt` |
| `Install_Labor_HackOHIO.xlsx`, `structure_drawings.pdf` | as supplied |
| `weather_cache.zip` | cached Open-Meteo responses, so `07_weather.py` runs instantly and doesn't hit the API |

The original package is in the organizers' repo `hackohio/aep_challenge_hack26` (`data/` + `docs/structure_drawings.pdf`) if you ever need `Customer_Clip` or a fresh copy.

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

### QA: attribution distance (`damage_attributed.csv` → `dist_m`)

Reviewed the distance from each damage point to the device it was attached to. **Attribution is sound; no fix needed.**

- All 1,648 records attributed. Overall `dist_m`: median 43 m, p90 160 m, p99 446 m, max 738 m (under the 1,000 m cap, so nothing is stretched past the documented limit).
- By method: `own_device` median **0 m** (406 recs), `secondary_to_transformer` median 31 m (156), `line_to_protective_zone` median 65 m / max 738 m (1,086 — the only method with a long tail, which is expected since it walks from a line/pole up to the first protective device).
- Only **15 records (0.9%) exceed 500 m**; **36 (2.2%) exceed 300 m**.
- The far matches are consistent with real rural line damage, not bad joins: among the >300 m records, **31/36 are from the Feb 2025 storm (E021)**, every >500 m record is `primary` wire or `Pole` (never equipment), and **29/36 had `Access_Iss = Yes`** vs ~32% overall. Remote, hard-to-reach span damage landing far from the nearest mapped device is physically sensible.
- Interpretation to state in the pitch: a large `line_to_protective_zone` distance means "this fault is somewhere in that device's zone," not "the device is that far from its own damage." Already reflected in `docs/ASSUMPTIONS.md`.
- Minor: the written `damage_attributed.csv` does not include a `report_day` column (only `event_id`). Add it to the `att[[...]]` selection in 03 if date-level QA is ever wanted.

## Device zone features: `08_features.py` → `device_features.csv`

One row per zone-owning device for the modeling team (v1 features, `pipelines/09_model_v1.py`). A **protective zone** is everything a fuse / recloser / breaker feeds downstream, stopping at the next protective device; transformers get a small local zone (themselves + what hangs directly off them). Reads `nodes.csv`/`edges.csv` (+ `nodes_base.csv` fallback), `Primary_ExportFeatures`, `Pole_Clip`, and `priority_nodes.csv`.

Line segments and poles carry no device ID, so they are assigned to a zone with the **same rule 03 uses for line/pole damage**: nearest transformer within 1,000 m (same circuit for primary lines) → that transformer's first upstream protective device. This keeps zone geography consistent with damage attribution.

Columns: `device_id, kind, circuit_id, lat, lon, n_customers, n_transformers, n_downstream_devices, n_poles, line_km, fail_prob, n_events_observed, critical`.

Current output on real data: **32,492 zones** (25,302 transformer + 6,757 fuse + 323 recloser + 110 breaker). Primary line assigned 3,779/5,121 km (74%); poles assigned 82,070/107,013 (77%) — the unassigned remainder is >1 km from any same-circuit transformer, the same limitation 03 has. 82 critical zones. `fail_prob`/`n_events_observed` are blank if 03 hasn't run; 204 rows (breakers, step transformers) have blank lat/lon, which is expected. **Nandan: add `python pipelines/08_features.py` to the Makefile `pipelines` target.**

## Utility operator console: `backend/app/console.py` + `frontend/src/console/`

Read-only internal view for AEP staff (not the customer UI). Operators need circuit IDs and equipment kinds, so those appear; but it stays read-only and never shows premise-level locations, contacts, or facility identities (only a count of critical zones).

| endpoint (GET) | returns |
|---|---|
| `/api/console/circuits` | every circuit with customers, device count, critical-zone count, storm-history depth (for the picker) |
| `/api/console/restoration/{circuit_id}?severity=&crews=` | protective devices ranked highest-priority-first (main-line first), with a representative model ETA. 404 on an unknown circuit |
| `/api/console/alerts?severity=&crews=&road_access=` | alert queue across circuits: risk-band counts, how many circuits meet the pre-storm threshold, and active escalations (uses a representative enrolled+medical profile per circuit — a what-if overview, not real sends) |
| `/api/console/audit?limit=` | tail of `logs/audit.jsonl`, newest first, every string scrubbed; declared needs reduced to a count so the tail can't profile an individual |

The UI is `frontend/src/console/Console.jsx` (+ its own `console.css`), fully self-contained so it touches no one else's files. Two one-line handoffs:
- **Nandan (main.py):** `from app.console import router as console_router` then `app.include_router(console_router)`.
- **Abby (App.jsx):** `import Console from "./console/Console.jsx"` and render it behind one tab button.

Tests: `backend/tests/test_console.py` **skip** until the router is registered, so they never red the build early; once Nandan adds the include line they run automatically (verified passing in-process). Demo note: most ARCOS "storms" are tiny, so bands only spread above ~the 95th severity percentile — set the console severity high (97+) to show High/Very High circuits.

## Open data: weather (`07_weather.py`, `backend/app/weather.py`)

| source | endpoint | used for | access |
|---|---|---|---|
| Open-Meteo Historical | `archive-api.open-meteo.com/v1/archive` | daily max gust, precipitation and snowfall per ~10 km cell over the ARCOS period → `weather_daily.csv`, `weather_events.csv`, `weather_reference.json` | no key; CC BY 4.0, credit "Weather data by Open-Meteo.com" |
| Open-Meteo Forecast | `api.open-meteo.com/v1/forecast` | live 3-day forecast in the UI | no key |
| National Weather Service | `api.weather.gov/alerts/active?point=…` | active warnings for the service area | no key; send a User-Agent |

- Raw API responses are cached in `data/processed/weather_cache/` (git-ignored). The first run of 07 takes ~6 minutes because requests are paced under Open-Meteo's per-minute limit; re-runs are instant.
- Only the coarse cell centres (means of transformer locations within each 0.1° cell) are sent to these services. No AEP IDs are sent.
- Findings and how weather is used: `docs/ASSUMPTIONS.md` → Weather.

## Priority facilities → `06_export_map_layers.py`

The 52 facilities are reprojected from the compound CRS and matched to the nearest transformer within 500 m: **41 matched** (4/5 hospitals, 30/37 fire, 7/10 ambulance). Only the transformer IDs are written (`priority_nodes.csv`); names, addresses and coordinates are dropped inside the script. They raise restoration priority and are never shown.

### QA: map-layer privacy review (`/api/map` → `map_layers.py`)

Audited the live `/api/map?severity=97` response against the real network. **Clean on all three requirements; no fix needed.**

- **No facility locations.** A text scan of the full 5.7 MB payload finds none of: hospital, fire, ambulance, medic, critical, address, road_name, owner, customer, premise_nu, phone, email, "life support". Critical facilities raise restoration priority inside the backend only; nothing about them reaches the browser.
- **One dot per transformer, not per home.** The response returns **25,300 points = exactly the transformers that have coordinates** (25,302 transformers total; 2 have no coordinate). That is far fewer than the 117,599 homes. Each point's `id` is a representative premise behind that transformer (every `id` is a premise node; 0 device IDs leak), and the point sits at the **transformer's** rounded coordinate, not the home's — spot-checked: point lat == transformer lat. So no home-level location is ever emitted.
- **No internal-only fields.** Premise points carry only `{id, lat, lon, circuit_id, n, p, band}`; circuits carry only `{circuit_id, lat, lon}`. No equipment IDs, no raw `fail_prob`, no operational columns. Coordinates are rounded to **4 decimals (~11 m)**, confirmed on the live payload.
- `circuit_id` is present (e.g. `0000027`) — this is an anonymized GIS circuit code, not a customer identifier, and the map needs it to color/select circuits. Acceptable for a customer-facing map; flagged here for completeness.

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
