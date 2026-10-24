# StormHaven assumptions

**Owner:** Akshat. This is the plain-English companion to [`config/assumptions.yaml`](../config/assumptions.yaml), the only place assumption values live. Change a value there and the outputs change. Keep this file in sync in the same PR, and announce changes in team chat because the file is shared.

**Source key**
- **AEP:** read from the AEP data package by a pipeline. The value is never typed into the repo.
- **AEP × assumed:** AEP numbers combined through a rule we chose.
- **assumed:** our choice, to be validated, ideally with an AEP mentor or by backtesting.
- **placeholder:** used only until the AEP file is loaded.

## Risk: "Will I lose power?"

**Model (real AEP data, `pipelines/03` + `engines/risk.py`).**
1. **Storms.** ARCOS has no storm IDs, so damage reported on days at most `event_gap_days` apart counts as one storm. That gives 36 storms; most are tiny and 3 are large.
2. **Storm size** m = records in the storm ÷ records in a typical (median) storm. The Feb 2025 storm is about 311× a typical storm.
3. **Damage attributed to devices** (see DATA_NOTES): the damaged device itself, or for line and pole damage, the protective device (fuse, recloser or breaker) that would open.
4. **Damage rate per device** in a typical storm, Gamma-Poisson empirical Bayes:
   *rateᵢ = (recordsᵢ + μₖβₖ) / (Σ storm sizes + βₖ)*, where μₖ (prior mean) and βₖ (prior strength) are estimated per device kind from the data. Devices with little history are pulled toward their kind's average. *pᵢ = 1 − e^(−rateᵢ)*. The shared code is `pipelines/_rates.py`.
5. **Scenario.** Severity percentile *s* maps to a storm size m(s) by reading the **real storm-size curve** (log-interpolated, held flat beyond the largest storm), then damped: *m_eff = m(s)^severity_damping*.
6. *pᵢ′ = 1 − (1 − pᵢ)^m_eff*, and *P(out) = 1 − ∏(1 − pᵢ′)* over the premise's upline path. Factors are each device's share of *−log(1 − pᵢ′)*.

On the synthetic network (no `meta.json`), step 5 uses *m(s) = exp(k·(s − 50)/50)* instead.

**Backtest (`pipelines/05`, leave-one-storm-out, storm size known):** Brier 0.0097 against 0.0113 for a constant-rate baseline. Calibration is good from 0–80% (predicted 7% → actual 7%, 37% → 32%, 61% → 59%). Predictions ≥ 80% are overconfident (91% → 48%, a small group). Within-storm ranking is modest (AUC 0.53–0.71 on the 3 large storms). Feb 2025: predicted 18.7% of premises out, actual 22.5%.

**Model v1 tested and not adopted (`pipelines/09_model_v1.py`).** v1 keeps the same structure, but pulls fuse, recloser and breaker zones toward a *feature-based* average instead of their kind's average. It's a Poisson regression on zone exposure from `08_features.py`: poles in the zone (strongest, +0.74 per SD), overhead km (+0.24), transformers (+0.16), underground share (−0.28). Pole age and wood share carried no signal. Same leave-one-storm-out backtest, everything re-fit without each storm:

| | v0 (served) | v1 |
|---|---|---|
| Brier / log loss | 0.00966 / 0.0430 | 0.00963 / 0.0423 |
| Feb 2025: predicted vs actual share out | 18.7% vs 22.5% | 20.8% vs 22.5% |
| AUC within storm: Feb 2025 / Sep 2024 / Jan 2025 | 0.711 / 0.664 / 0.532 | 0.697 / 0.662 / 0.548 |

v1 is marginally better on average but not at picking *which* areas go dark within a storm, the weakness it was meant to fix. Where damage lands inside a big storm seems to depend on where the ice and wind hit, and a zone's history already reflects its exposure. **Rule: keep the simpler model unless the richer one wins on held-out storms → `risk.model: v0`.** Switching is one config line, and 09 reports both models on every run.

| key | value | meaning | source | how we validate |
|---|---|---|---|---|
| `risk.model` | v0 | which damage-rate model `09` writes into `nodes.csv` (v0's values are always kept in `fail_prob_v0`) | backtest decision | re-run 09 after data or feature changes |
| `risk.bands` | Low < 0.20 ≤ Moderate < 0.50 ≤ High < 0.80 ≤ Very High | probability cut-offs for the customer-facing band | assumed | backtest: observed rates differ clearly by band; note "Very High" is overconfident |
| (data) severity curve | `meta.json` from 03 | percentile → storm size, from the 36 real storms | AEP | — |
| `risk.severity_damping` | 0.8 | outage probability uses m(s)^0.8: big storms cluster damage, so fewer distinct customers go out than damage counts suggest | fit on AEP data (best Brier and log loss of 1.0/0.9/0.8/0.7/0.6 in 05; in-sample for this one parameter) | re-run 05 after any data or model change |
| `risk.event_gap_days` | 1 | report days at most this far apart = one storm (gaps of 1, 2 and 3 days give 35–36 storms, so the result is not sensitive to this) | assumed | team decision |
| `risk.severity_k` | 1.2 | synthetic network only: exponential severity curve | assumed | — |
| `risk.prior_failure_prob` | 0.02 | only if a device has **no** `fail_prob` value at all (never happens with 03 output) | assumed | — |
| (data) per-kind prior μₖ, βₖ | from 03 (`meta.json` → `kind_priors`) | e.g. reclosers fail ~100× more often per device than transformers (their zone covers more line). Step transformers have no records and borrow the transformer prior | AEP | — |
| `risk.confidence.high_min_events` | 5 | storms that damaged anything on the customer's circuit, for **High** | assumed, set from data | gives ~16% High / 52% Medium / 32% Low across premises |
| `risk.confidence.medium_min_events` | 2 | same, for **Medium**. Low = this circuit was damaged in at most 1 recorded storm | assumed, set from data | 8/3 (the old values) put 52% of customers at Low, triggering the human-callback escalation for half the territory |
| (code) extreme storm | *s* > 95 or < 5 → confidence drops one level, with "Only a few past storms were this severe…" | only ~2 storms above the 95th percentile | assumed | — |
| (code) circuit-level match | circuit, not premise → confidence drops one level | the answer is for a representative premise | assumed | — |
| (code) Very High caveat | real data and P(out) ≥ 0.8 → "Our very high estimates have run high in past storms: read this as 'likely', not 'certain'." | the backtest's ≥ 80% bin came true ~48% of the time | from backtest | — |

**Storm severity percentile *s*** is a scenario input, not a live forecast. It is the storm's rank among the 36 recorded ARCOS storms, so the 99th percentile ≈ the Feb 2025 storm. Because most recorded "storms" are tiny, everything below about the 90th percentile looks calm; the UI defaults to 97. Whether to rank only among major storms is a team decision.

**ARCOS attribution parameters** (in `03_build_labels.py`): own-device match within 100 m (fuse, transformer) or 150 m (recloser); line, pole and secondary damage → nearest transformer within 1,000 m (the largest observed distance is about 740 m). Light and capacitor-bank records are dropped as non-interrupting.

## Weather (Open-Meteo history, `pipelines/07_weather.py`): context, not a model input

We pulled daily weather for the whole ARCOS period on ~10 km cells over the service area (26 cells × 1,432 days) and tested it honestly:

| question | result | decision |
|---|---|---|
| Does wind predict **whether** damage happens? | Yes. Damage was reported within 2 days after **6%** of days with median-cell gusts < 30 mph, **14%** at 30–40 mph, and **31%** at ≥ 40 mph. | Shown in the forecast card ("on past days this windy…") |
| Does weather predict **how much** damage (storm size)? | Barely. A leave-one-storm-out Poisson model on gusts has mean log error 0.82 vs 0.99 for "a typical storm". Adding rain or snow makes it worse (overfitting with 36 storms). It predicts ~10–20 records for Feb 2025 (actual 1,244), whose worst days followed a snow/ice event rather than the windiest day. | **Weather does not set severity.** The slider stays a storm-size percentile. |
| Within a storm, do windier areas get more damage? | Mixed: rank correlation 0.46 across cells in Feb 2025, 0.16 in Sep 2024, −0.08 in Jan 2025. | Not used yet. Candidate improvement once there's more than 3 large storms of evidence. |

What the app does with weather: (1) labels the severity slider with the closest real storm ("Similar to the Sep 2024 storm: gusts up to 56 mph, 94 mm rain"); (2) shows the live 3-day forecast and active NWS warnings for the area, with the historical damage odds for that much wind. Neither changes a risk or restoration number.

| setting (in `07_weather.py`) | value | meaning |
|---|---|---|
| cell size | 0.1° (~10 km) | about the resolution of the weather model |
| `REFERENCE_MIN_RECORDS` | 10 | storms used to label the slider (10 storms) |
| `REPORT_LAG_DAYS` | 2 | ARCOS reports trail the weather by up to ~2 days |
| `GUST_BINS` | < 30, 30–40, ≥ 40 mph | coarse on purpose: only 70 days had ≥ 40 mph median-cell gusts |

## Restoration: "How long could it take?"

Model: Monte Carlo (`n_simulations` draws) over damage on the premise's upline path, conditioned on the premise losing power.
For each damaged device: **clock hours = (qty × labor_hours[type] + access_adder) × indirect_multiplier ÷ crew_size × access_multiplier × lognormal noise**, where qty is 1–2.
**Queue wait** = storm-wide backlog × (1 − the device's priority percentile) ÷ crews × access_multiplier. Priority = customers restored, plus a bonus if the device feeds a critical facility. This is step restoration: main-line repairs go first.
**Storm-wide backlog** (real data) = expected damage records in a storm this size (median records × undamped m(s)) × average person-hours per record (AEP labor × the ARCOS damage-type mix) × indirect multiplier ÷ crew size. On the synthetic network it is `base_backlog_hours_per_crew` × `default_crews` × m(s).
**Restore time** = assessment hours + the maximum over damaged devices of (wait + labor). We report P10, P50 and P90, plus drivers: the change in P50 with 50% more crews, with blocked roads, and with a storm 20 percentiles stronger. Before an outage the range is phrased "If you lose power…"; once the (simulated) utility feed confirms an outage it becomes "Our estimate: power back in…" and stays labeled as a model estimate.

| key | value | meaning | source | how we validate |
|---|---|---|---|---|
| `restoration.n_simulations` | 600 | Monte Carlo draws (drivers use 300 with the same seed) | assumed | P50 should be stable to ±0.5 h across seeds |
| `restoration.assessment_hours` | 2.0 | damage assessment before any crew is dispatched | assumed | ARCOS report-to-first-repair gap, if timestamps allow |
| `restoration.labor_noise_sigma` | 0.30 | lognormal spread on each repair's labor | assumed | P10–P90 coverage of ARCOS repair durations (05) |
| `restoration.crew_size_persons` | 3 | people per line crew. Converts AEP **person**-hours to clock hours | assumed | **ask an AEP mentor** whether the CU hours are per person or per crew |
| `restoration.default_indirect_labor_multiplier` | 3.0 | used only if `multipliers.json` is missing | placeholder | replaced by the AEP sheet value once 04 runs |
| (data) indirect labor multiplier | from the AEP workbook, sheet *Indirect Labor Multiplier* | drive + safety discussion + setup time, multiplied onto every labor hour | AEP | — |
| `restoration.access_multipliers` | normal 1.0 / limited 1.4 / blocked 2.2 | storm-wide access slowdown (detours, tree clearing), applied to labor **and** queue wait | assumed | sensitivity check only; AEP gave no storm-access data |
| (data) access adders | sheet *Labor only work*. limited → "Access Constraint Adder", blocked → "Remote Location Adder" | person-hours added per job | AEP × assumed (the mapping is ours) | — |
| `restoration.base_backlog_hours_per_crew` | 10.0 | **synthetic network only**: backlog per crew at a median storm | assumed | — |
| `restoration.default_crews` | 20 | synthetic backlog sizing; the UI's starting crew count is also 20 | assumed | **ask AEP** for typical storm crew counts; the restoration backtest is blocked until `Repaired_D` is understood |
| `restoration.critical_facility_priority_bonus` | 5000 | customer-equivalents added to devices feeding hospitals, fire or EMS | assumed | — |
| `restoration.unknown_damage_type_hours` | 4.0 | person-hours when a damage type has no labor entry | assumed | the share of ARCOS records hitting this fallback should be ≈ 0 after `DAMAGE_NAME_MAP` |
| `restoration.repair_recipes` (incl. `fuse_cutout_damaged` = cutout replace, `switch_damaged` = switch replace, added for ARCOS types) | e.g. broken pole = medium pole + crossarm + 3 insulators + 3 pins + grounding + guy + anchor | which compatible units (CUs) a crew replaces for each damage type. `04_load_labor.py` sums the AEP CU hours over each recipe | AEP × assumed | **check against the AEP structure-diagram PDF** and with a mentor |
| `restoration.non_cu_hours.tree_on_line` | 3.0 | person-hours for tree removal (no CU in the AEP sheet) | assumed | ask a mentor |
| `restoration.placeholder_labor_hours` | 0.5–6.0 per type | used only before `04_load_labor.py` has run | placeholder | — |

## Guidance: "What should I do?"

Rules, not generation: risk band × duration bucket × **declared** needs select items from `backend/app/content/guidance_library.yaml`. Every item cites a source. The LLM may only select and rephrase.

| key | value | meaning | source |
|---|---|---|---|
| `guidance.duration_buckets` | short < 4 h ≤ day < 24 h ≤ multi_day < 72 h ≤ extended (on P90) | which advice applies, e.g. water storage for day+ | assumed (matches FoodSafety.gov 4 h fridge / 48 h freezer guidance) |
| (code) fallback bucket | unknown location → treated as a day-long outage | advice errs on the safe side | assumed |

## Alerts: "Do I qualify?"

| key | value | meaning | source |
|---|---|---|---|
| `alerts.eligibility.require_enrollment` / `require_valid_channel` | true / true | eligible = enrolled AND has a contact channel | assumed (documented challenge rule) |
| `alerts.eligibility.min_risk_band` | Moderate | pre-storm alerts at or above this band, **or** if a medical or critical need is declared | assumed |
| `alerts.timing.pre_storm_hours_before` | 36, 8 | pre-storm alert times before expected landfall | assumed |
| `alerts.timing.outage_confirmed_within_minutes` | 15 | outage-confirmed alert delay | assumed |
| `alerts.timing.estimate_update_threshold_hours` | 1.0 | re-alert only if the estimate moves more than this | assumed |
| `alerts.escalation.medical_need_outage_hours` | 4 | declared medical need + P50 above this → human callback | assumed |
| `alerts.escalation.etr_missed_grace_hours` | 1 | missed estimate by more than this → apology + new estimate | assumed |
| `alerts.sms_max_chars` | 320 | hard cap after scrubbing (2 SMS segments) | assumed |
| (code) other escalations | downed line → 911 + emergency queue; Low confidence → fallback message + human contact | — | assumed |

## Privacy

| key | meaning |
|---|---|
| `privacy.llm_field_allowlist` | the only derived fields Bedrock ever receives: band, probability, confidence, factor text, P10/P50/P90, drivers, step text, declared needs, eligibility, assumptions, missing data, curated guidance text. No IDs, no coordinates, no facility data. |
| (code) `scrub_text` | removes coordinates, internal equipment IDs, phone numbers and emails from every customer-facing string and every SMS |
| (code) map | premise coordinates rounded to 4 decimals; critical facilities never sent |

## Known simplifications (say these out loud in the pitch)
1. Damage on different devices is treated as independent within a storm. Real storms cluster damage spatially; `severity_damping` corrects the average effect, but predictions above 80% remain overconfident.
2. One parent per node: radial network, with no switching or back-feed. Real crews can sometimes re-route power, which would shorten some outages.
3. Queue wait uses a single storm-wide backlog, not a real crew dispatch schedule.
4. Storm severity is one number, not wind, ice or track.
5. Storm history is thin: 36 recorded storms, only 3 large. The model learns *where* damage happens mostly from one storm (Feb 2025, ~75% of all records).
6. ARCOS gives damage locations, not customer outage records. "Out" means "damage on your upline path"; partial-phase or momentary outages aren't captured.
7. Restoration ranges are not yet backtested: ARCOS repair dates look like record-closure dates (see DATA_NOTES).
