# StormHaven: judge Q&A prep

**Owner:** Akshat. Short, honest answers to the questions judges are most likely to ask, grouped by judging value. Rule of thumb: **state the number, state the limit, point to where it's documented.** Never claim more than the backtest shows.

## The big picture
**What is StormHaven, in one breath?**
A customer storm assistant on real AEP data. For your home it answers: will I lose power, how long, what should I do, and will I be alerted. Every number comes from deterministic models built on AEP's topology, damage history and labor standards. The AI only routes your question; it never invents a number.

**Who is it for?**
Residential customers, on their phone, before and during a storm. The same engines also produce the utility's storm-wide view (the crew planner), which reaches the customer as one sentence about how fast homes came back in a similar storm.

## Operational realism
**How do you know who loses power?**
AEP's `matched_upstream.txt` gives each premise's chain of equipment up to the circuit breaker. If anything on your chain is damaged, you're out. 117,599 premises, 110 circuits.

**Where do repair times come from?**
The AEP data guide's chain, exactly:
1. Damage record → nearest mapped pole (height → small/medium/large).
2. Nearest primary line (phases → single vs three-phase).
3. Structure drawings → construction units → `Install_Labor_HackOHIO.xlsx` hours → × 4.5 indirect multiplier = person-hours.

A medium three-phase pole replacement = **26.3 person-hours** (the guide's example: 27).

**What is step restoration in your model?**
A customer is back as soon as every damaged device on *their* path is fixed, not when the whole circuit is. Crews take the job with the most customers restored per crew-hour, and hospitals, fire and EMS jump the queue. Feb 2025 replay with 20 crews: half of customers back in ~16 h, 90% in ~3 days, the last ones in ~8 days.

**How many crews would AEP need?**
Feb 2025 replay (11,800 person-hours): everyone back in **2 days needs ~291 line workers, 3 days ~180, 1 week ~75** (crews of 3). See `docs/figures/4_crews_needed.png`.

**Why crews of 3, and why 20 crews?**
Both are stated assumptions; the mentors weren't available to confirm. The guide says 2–8 per crew; we use 3. For this ~118k-customer area we assume 20 local crews (60 line workers) before mutual aid. "What if AEP brings in extra crews?" shows the effect. The planner shows the full trade-off: restoring everyone in 3 days takes ~180 people.

**What about switching / back-feed?**
Not modeled. The switch layer isn't in the topology file. Real crews can re-route power, so for some customers we're conservative. Disclosed as a known simplification.

**Why is the restoration range so wide?**
Because that's honest. It comes from Monte Carlo over which equipment fails, what damage type it is, repair-time variability, and the queue ahead of you. We never show a single promised time, and the customer range is calibrated on the storm replay: the typical home's best guess (15 h) matches the replay's 50% point (16 h) for Feb 2025.

## AI + data / modernization
**What does the AI actually do?**
Amazon Nova Lite on Bedrock, with a Guardrail, classifies your question and may request one validated what-if (storm strength, crews, roads). Python renders every fact from the engines. Model-generated outage prose is never shown.

**Why Nova and not a bigger model?**
Deliberate. The AI's job is narrow (routing), so a fast, cheap model with a Guardrail is the responsible choice. A bigger model would add cost and latency without adding accuracy, since it doesn't compute anything.

**Is it machine learning?**
Yes, statistical learning: each device's damage rate is learned from 36 real storms with an empirical-Bayes (Gamma-Poisson) model that pulls sparse devices toward their type's average, weighted by storm size. We also built a richer feature model (v1: poles, overhead line, underground share) and **kept the simpler one because it didn't win on storms it hadn't seen**.

**How accurate is the risk model?**
Leave-one-storm-out backtest over 4.2 million premise-storm pairs:
- **Brier score:** 0.0097, vs 0.0113 for a constant-rate baseline.
- **Calibration:** good from 0–80%.
- **Feb 2025** (held out): predicted 18.7% of customers out, actual 22.5%.
- **The limit:** predictions of 80%+ came true about half the time. The app says so on those answers ("read this as 'likely', not 'certain'").

See `docs/figures/1_calibration.png` and `2_heldout_storms.png`.

**Why is "storm strength" a percentile and not wind speed?**
We tested weather (Open-Meteo, 26 cells × 4 years). Wind predicts *whether* damage happens (damage after 6% of calm days vs 31% of days with 40+ mph gusts) but not *how much*. It predicted ~15 records for Feb 2025, which actually had 1,244, an ice-then-wind event. So severity is ranked against real storm history, and weather is shown as context.

**Only 36 storms, 3 of them large. Isn't that thin?**
Yes, and we say so. That's why we use shrinkage (sparse devices borrow from their type), test on held-out storms, and show ranges and confidence instead of point predictions.

## Responsible AI / privacy / safety
**What customer data do you use?**
None from the customer file. It contains addresses and life-support flags, and we deliberately never read it. Customers identify themselves with the premise ID from their bill. Medical or other needs are **opt-in checkboxes only**, never inferred.

**Can I see where hospitals are?**
No. Facility locations never leave the backend. They only raise restoration priority for the transformer that serves them.

**Does the map expose homes?**
No. Each dot is a neighborhood transformer, not a home.

**What stops the AI saying something unsafe?**
- The Bedrock Guardrail.
- The AI never writes outage facts; Python renders them.
- Every customer-facing string is scrubbed for IDs, coordinates and contacts.
- Emergency words ("downed line", "sparking", "fire") get a fixed 911 message added in code, even if Bedrock is down.

**What happens when you can't predict?**
An honest fallback: no numbers, "we can't make a reliable prediction for this location", and pointers to AEP's official channels. Low confidence triggers a human-contact escalation.

**How do you separate estimates from facts?**
Three columns: *Confirmed by AEP* (only from the utility's status feed, simulated in the demo) / *Our estimate* (labeled as a model estimate, with confidence, assumptions and limits) / *What you can do*.

**Can I look up someone else's house?**
You can see a neighborhood's outlook, which is infrastructure information, like a utility's public outage map. Map dots are anonymous neighborhood tokens, never premise numbers or homes. Personal features (alerts, texts, declared needs) only follow when you enter your own premise ID. In production, premise lookup would sit behind AEP account login; we say that openly.

**Why does the public website show a different (demo) network?**
The internet-facing deployment runs in a fail-closed demo mode on a synthetic network, so no AEP data is ever exposed publicly. The real-data version runs privately (the video and live demo use it). That's privacy by design, not a gap.

**Why does the customer pick the storm strength?**
They don't. The banner shows the forecast scenario ("planning for a severe storm, similar to Sep 2024"). "What if…?" lets them see how much a stronger storm, blocked roads or extra crews would change their answer. The engines learn *where* damage happens from AEP history; *how strong* the storm is comes from the forecast.

**What if someone depends on medical equipment?**
They can opt in by ticking "Powered medical equipment" and, optionally, telling us how long its battery lasts. We compare that with *their* restoration range. If the battery may run out (shorter than our best guess, or than the pessimistic end), the warning goes first and AEP's priority-call escalation switches on. We never ask about health unprompted and never infer it.

**Where is "confirmed by AEP" vs your estimate?**
A strip above the estimate cards says either "No outage confirmed at your location yet. Everything below is our estimate." or shows the utility's confirmed time (simulated in the demo). Confirmed facts, model estimates and customer actions are three visibly separate things.

## Known simplifications (say them before they're found)
These are listed in `docs/ASSUMPTIONS.md` → "Known simplifications":
- damage treated as independent across devices
- no switching or back-feed
- one storm-wide queue
- severity is one number
- thin storm history
- damage locations are used as an outage proxy
- restoration ranges not backtested
- the replay assumes crews work around the clock

**Why isn't restoration backtested?**
ARCOS repair dates are whole days and look like record-closure dates (median 21–23 days in two storms, 1 day in another). We treat `Repaired_D` as a record-closure date, not a power-restored time, so we don't score restoration against it. That's a stated assumption, and we'd rather say it than fit to it blindly.

## If a judge asks for a live change
- **Customer view:** "What if roads are blocked?" → the range widens and the reason appears.
- **Medical device ticked** → advice changes and a human escalation appears.
- **Planner:** crews 20 → 60 → everyone back in ~3 days instead of ~8.
