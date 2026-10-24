# Upline spot-check (manual QA)

<!-- PRIVACY NOTE (Abby, QA fix #1): this doc is committed, so per our data rule it must contain NO real
     premise numbers, device IDs, or absolute coordinates. Premises are relabelled A/B/C, devices by kind
     only, and every location is given as a RELATIVE distance (step from the previous device / running total),
     never a lat/lon. The findings are unchanged — only the identifiers were anonymized.
     To re-run the raw check locally (never commit its output), sample premises from data/processed/nodes.csv
     and walk edges.csv with core/topology.upline_path. -->

Three premises of increasing path depth, each with its upline chain of devices nearest→substation.
`step` = straight-line distance from the previous device; `cum` = running distance from the home.

How to read it: a radial feeder should march roughly in one direction, with steps of tens-to-hundreds of
metres, growing to a few km by the breaker. Watch for a single huge jump (a possible mis-join) or a device
that doubles back far from the rest. (Done locally with real coordinates; only distances are recorded here.)

---

## Premise A — a short circuit — 2 devices (shortest)
Home → transformer (same location) → breaker (no coordinate).
Trivial path, nothing to question. The breaker has no coordinate — expected, because breakers carry no point
in the GIS layers.

## Premise B — a suburban circuit — 4 devices
```
transformer   (home's location)
fuse          step ~575 m
recloser      step ~575 m   (cum ~1.1 km)
breaker       (no coordinate)
```
Looks good: ~0.5 km hops staying within a ~1 km neighborhood, consistent with a single feeder.

## Premise C — a long rural circuit — 9 devices (longest) — ⚠ ONE JUMP TO CHECK
```
transformer   (home's location)
fuse          step ~245 m
fuse          step ~706 m
fuse          step ~139 m
fuse          step ~480 m
recloser      step ~191 m    <- devices 1-6 cluster within ~1.8 km, all sensible
recloser      step ~7 km     <- ⚠ large jump
recloser      step ~229 m
breaker       (no coordinate)
```
The first six devices form a tight, sensible chain. Then there is a **~7 km jump** to the last two reclosers
near the substation. This is **plausible, not necessarily wrong**: this is one of the long, wooded rural
feeders, so a long backbone run from the last neighborhood recloser down to the substation-side reclosers is
realistic. But it is the kind of hop worth verifying on a map — confirm there is a feeder corridor between the
two points, not two unrelated areas stitched together.

---

### Verdict
2 of 3 paths are clean. The third has one long backbone hop that is consistent with a long rural feeder but
is the single thing worth a human look on a map.

**Confirmed (manual):** the ~7 km hop on Premise C's circuit was checked on a map. The two reclosers are
joined by a single continuous ~5-mile (~7.7 km by road) rural road corridor that follows the terrain — a
believable feeder backbone, not two unrelated areas. The `02` topology join is behaving as intended.
Spot-check **passed**.

Re-run the sampling on more premises if wider coverage is wanted before the pitch.
