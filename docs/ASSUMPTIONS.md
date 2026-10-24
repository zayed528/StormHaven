# StormHaven assumptions

**Owner:** Akshat. This is the plain-English companion to [`config/assumptions.yaml`](../config/assumptions.yaml), the only place assumption values live. Change a value there and the outputs change. Keep this file in sync in the same PR, and announce changes in team chat because the file is shared.

**Source key**
- **AEP:** read from the AEP data package by a pipeline. The value is never typed into the repo.
- **AEP × assumed:** AEP numbers combined through a rule we chose.
- **assumed:** our choice, to be validated, ideally with an AEP mentor or by backtesting.
- **placeholder:** used only until the AEP file is loaded.

## Risk: "Will I lose power?"

Model (v0): every device *i* on the premise's upline path has a historical per-storm failure probability *pᵢ*, the share of past events with ARCOS damage on that device. A storm at severity percentile *s* scales it: *pᵢ′ = 1 − (1 − pᵢ)^m(s)* with *m(s) = exp(k·(s − 50)/50)*. The premise is out if any device fails: *P(out) = 1 − ∏(1 − pᵢ′)*. The factors shown are each device's share of the total hazard *−log(1 − pᵢ′)*.

| key | value | meaning | source | how we validate |
|---|---|---|---|---|
| `risk.bands` | Low < 0.20 ≤ Moderate < 0.50 ≤ High < 0.80 ≤ Very High | probability cut-offs for the customer-facing band | assumed | the bands should split backtest premises into groups with clearly different observed outage rates |
| `risk.severity_k` | 1.2 | how strongly storm severity scales failure odds. At *s* = 90 the multiplier is ≈ 2.6×; at *s* = 10 it is ≈ 0.38× | assumed | fit *k* on ARCOS: regress per-event damage counts on the event's severity percentile (05) |
| `risk.prior_failure_prob` | 0.02 | failure probability for a device with no history | assumed | compare with the ARCOS base rate across all devices |
| `risk.confidence.high_min_events` | 8 | median events of history on the path for **High** confidence | assumed | backtest: calibration error should be lower for High than for Medium |
| `risk.confidence.medium_min_events` | 3 | same, for **Medium** | assumed | same |
| (code) out-of-range storm | *s* > 95 or < 5 → confidence drops one level | we have few storms that extreme | assumed | — |
| (code) circuit-level match | circuit, not premise → confidence drops one level | the answer is for a representative premise on the circuit | assumed | — |

**Storm severity percentile *s*** is a scenario input, not a live forecast. Once ARCOS arrives, Akshat defines it as the percentile of an event's total damage count among past events, so "90th percentile" means "worse than 90% of storms in the history".

## Restoration: "How long could it take?"

Model: Monte Carlo (`n_simulations` draws) over damage on the premise's upline path, conditioned on the premise losing power.
For each damaged device: **clock hours = (qty × labor_hours[type] + access_adder) × indirect_multiplier ÷ crew_size × access_multiplier × lognormal noise**, where qty is 1–2.
**Queue wait** = storm-wide backlog × (1 − the device's priority percentile) ÷ crews × access_multiplier. Priority = customers restored, plus a bonus if the device feeds a critical facility. This is step restoration: main-line repairs go first.
**Restore time** = assessment hours + the maximum over damaged devices of (wait + labor). We report P10, P50 and P90, plus drivers: the change in P50 with 50% more crews, with blocked roads, and with a storm 20 percentiles stronger.

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
| `restoration.base_backlog_hours_per_crew` | 10.0 | storm-wide backlog per crew at a median storm, scaled by severity | assumed | fit so median simulated restoration ≈ median ARCOS event duration |
| `restoration.default_crews` | 20 | crew count the backlog is sized for | assumed | ask AEP for typical storm crew counts per district |
| `restoration.critical_facility_priority_bonus` | 5000 | customer-equivalents added to devices feeding hospitals, fire or EMS | assumed | — |
| `restoration.unknown_damage_type_hours` | 4.0 | person-hours when a damage type has no labor entry | assumed | the share of ARCOS records hitting this fallback should be ≈ 0 after `DAMAGE_NAME_MAP` |
| `restoration.repair_recipes` | e.g. broken pole = medium pole + crossarm + 3 insulators + 3 pins + grounding + guy + anchor | which compatible units (CUs) a crew replaces for each damage type. `04_load_labor.py` sums the AEP CU hours over each recipe | AEP × assumed | **check against the AEP structure-diagram PDF** and with a mentor |
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
1. Damage events on different devices are treated as independent within a storm. Real storms cluster spatially, so this likely understates the chance of multiple failures.
2. One parent per node: radial network, with no switching or back-feed. Real crews can sometimes re-route power, which would shorten some outages.
3. Queue wait uses a single storm-wide backlog, not a real crew dispatch schedule.
4. Storm severity is one number, not wind, ice or track.
