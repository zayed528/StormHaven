# Upline spot-check (manual QA)

Three premises of increasing path depth, with each upline device's coordinates nearest→substation.
To eyeball: paste the "all coords" line for a premise into Google Maps (or geojson.io) and confirm the
points form a sensible line toward the substation. `step_m` = distance from the previous device;
`cum_m` = running distance from the home.

How to read it: a radial feeder should march roughly in one direction, steps of tens-to-hundreds of metres,
growing to a few km by the breaker. Watch for a single huge jump (possible mis-join) or a device that
doubles back far from the rest.

---

## PREMISE 017736277 — circuit 0000094 — 2 devices (shortest)
Home (37.26036, -79.93548) → transformer `XF-144122562` (same coord) → breaker `CB-157965178` (no coord).
Trivial path, nothing to question. Breaker has no coordinate (expected: breakers carry no point in the GIS).

## PREMISE 442644863 — circuit 0000041 — 4 devices
```
transformer 37.29259,-80.02204
fuse        37.28944,-80.01690   (575 m)
recloser    37.29023,-80.02332   (575 m, cum 1149 m)
breaker     (no coord)
```
Looks good: ~0.5 km hops staying within a ~1 km neighborhood, consistent with one feeder.

## PREMISE 432989923 — circuit 0000005 — 9 devices (longest) — ⚠ ONE JUMP TO CHECK
```
transformer 37.32414,-79.74416
fuse        37.32621,-79.74320  (245 m)
fuse        37.32146,-79.73790  (706 m)
fuse        37.32027,-79.73744  (139 m)
fuse        37.31607,-79.73624  (480 m)
recloser    37.31460,-79.73512  (191 m)   <- devices 1-6 cluster within ~1.8 km, all sensible
recloser    37.27232,-79.79319  (6963 m)  <- ⚠ 7 km jump
recloser    37.27027,-79.79306  (229 m)
breaker     (no coord)
```
The first six devices form a tight, sensible chain. Then there's a **~7 km jump** to the last two reclosers
near the substation. This is **plausible, not necessarily wrong**: rural circuit 0000005 is long and wooded
(it's one of the longest feeders), so a long backbone run from the last neighborhood recloser down to the
substation-side reclosers is realistic. But it's the kind of hop to verify — paste those two coords into a
map and confirm there's a feeder corridor between them, not two unrelated areas stitched together.

---

### Verdict
2 of 3 paths are clean. The third has one long backbone hop that is consistent with a long rural feeder but
is the single thing worth a human look on a map.

**Confirmed (manual, Jaid):** the ~7 km hop on circuit 0000005 was checked on Google Maps. The two reclosers
(near Bore Auger Rd → Stewartsville) are joined by a single continuous ~4.8-mile rural road corridor following
the terrain past Jordantown — a believable feeder backbone, not two unrelated areas. The `02` topology join is
behaving as intended. Spot-check **passed**.

Re-run the sampling on more premises if wider coverage is wanted before the pitch.
