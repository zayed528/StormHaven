# StormHaven demo script

**Owner:** Nandan (script). **Presenter:** Akshat. Target: **5 minutes**, then Q&A. Rehearse at least 3 times (hours 20–24).
Each step names the minimum-viable-demo (MVD) step it proves. The judges' rule "change at least one scenario input and see the response change" is covered in step 3.

**Setup before going on stage**
- `make api` + `make web` on the demo laptop, **and** a deployed URL as backup, **and** the backup video (recorded by hour 22).
- Browser zoom 110%. Close other tabs. Phone with the SNS sandbox number on the table, volume on.
- Empty `logs/audit.jsonl` so the utility console's audit log starts clean.
- Reset the page: storm level **High risk** (the default), no needs ticked, "Signed up for text alerts" on, demo toggle off, **English**, **Risk dots** view, map flat.
- Theme: try **Light** and **Dark** (bottom-left sun / moon) on the actual projector and keep whichever reads better. Projectors often wash out dark themes.
- Know the demo premise IDs (real data): one High dot in the southern circuits and one Low. Write them on a card; don't show premise IDs on slides.
- The storm levels are ranks among the 36 storms recorded in ARCOS: **Low risk** (median storm), **Moderate risk** (95th), **High risk** (97th), **Extremely high risk** (99th, about the Feb 2025 storm). Below Moderate almost everything is calm, which is honest but dull, so stay on High and Extremely high on stage.
- The storm level says how bad the *storm* is; the band in the results (Low / Moderate / High / Very High) is *Maria's* outage risk. If a judge asks why they differ, that's the answer: a big storm doesn't put every home at high risk.

---

### 1. Pick a location (MVD 1) ~20 s
> "A storm is 36 hours out. Maria wants to know what it means for *her* home."
- Click a red or orange dot (each dot = one neighborhood transformer and its homes), or type the premise ID in "Or enter your premise ID".
- Point out: anonymized IDs only; the map shows risk bands, never hospitals or fire stations.

### 2. "Will I lose power?" (MVD 2) ~40 s
- The safety banner is tinted to her risk. Read the band and confidence aloud: "**High outage risk, Medium confidence**."
- Point to **Why**: equipment history on *her* line, storm strength, path exposure.
- Open **Assumptions, missing data, and limits** for 3 seconds: "every number traces back to `assumptions.yaml`."

### 3. Change the storm → restoration range (MVD 3) ~60 s, **judges' interaction**
- Read the range: "If you lose power, most likely X to Y hours. **A range, not a promise**."
- Drag **Storm level** from **High risk** to **Extremely high risk**. The map reddens, and the risk line and the range **light up yellow with "Was: …"**, so the audience sees exactly what moved.
- Point at the **"what if" lines** under the range ("about N hours sooner if 50% more crews are available", "later if fallen trees block roads"): crews and road access still drive the estimate; the customer just doesn't have to set them.
- Point at the **step timeline**: the shaded likely range, the best-guess line, and the marker where *her* power returns. The main line is fixed first, so the steps never go backwards. That's step restoration.
- **Offer a judge the slider.**
- *(If time, ~10 s)* Click **Heatmap**: "where the most homes are likely to lose power." Right-click and drag on the map for a tilted 3D view, then switch back to **Risk dots**.

### 4. Prepare + alert eligibility (MVD 4) ~40 s
- Show **What you can do**: actions change with risk and duration (water storage appears for day-plus outages).
- Tick **Powered medical equipment** (opt-in, never inferred) → medical battery and backup-plan items appear, a medical **Safety** item appears, and "**We'll follow up personally**" shows the human callback escalation.
- Read **Alerts**: eligible because she's enrolled and has a channel.

*(Optional, if real weather is happening on demo day: point at the live forecast card and any NWS warning. "This is today's real forecast for the area. It's context; you choose the scenario.")*

### 5. Proactive communication (MVD 5) ~40 s
- Show the **Before the storm** message.
- Tick **Demo only → Simulate: the utility confirms an outage**. The **Demo utility status** column fills, labeled as a simulation, still separate from **Our estimate**.
- Move the storm level again → the **Estimate updated** message shows old → new range *and the real reason* ("the storm forecast got stronger").
- Click **Send this alert as a text** under a message. With SNS live the phone buzzes; without it the page shows "Dry run" and the exact text that would be sent. Say which one it is.

### 6. Trust: privacy, safety, uncertainty, limits (MVD 6) ~50 s
- Open the chat (robot, bottom-right). In chat: "**There's a downed wire sparking in my yard**" → the reply **starts with a fixed 911 safety message** (not LLM-written).
- In chat: "Where is the nearest hospital on my circuit?" → no location is revealed. Facility locations never leave the backend, so neither the API nor the LLM has them, and the system prompt prevents disclosure. (Rehearse this with Bedrock on; offline mode just repeats the outlook.)
- Type a made-up premise ID → **fallback**: "We can't make a reliable prediction... check AEP's outage map." No made-up numbers.
- Click **Español** (top right): the whole page, the chat and the text messages switch to Spanish. Switch back.
- One line: "The LLM never writes an outage fact. It selects the relevant engine answer and can request one validated what-if; Python renders the exact values. We minimize and best-effort scrub the latest question before Bedrock receives it."

### 7. Utility console ~20 s
- Click **Utility console**. Move its storm level: the number of homes getting a pre-storm alert and the homes-by-risk-band counts follow the storm.
- Pick a circuit: the restoration order (critical facilities flagged, never located). Point at the **audit log**: Maria's prediction from step 1 is there.

### 8. Close: credibility + modernization ~30 s
- Backtest slide (from `05`): calibration and restoration-range coverage. If 05 didn't run on real data, show the synthetic-only caveat honestly.
- Architecture in one breath: AEP topology + ARCOS history + labor sheets → 4 deterministic engines → Nova Lite on Bedrock routes the question → Python renders verified facts → SNS alerts → audit trail.
- "Built for everyone: English and Spanish, keyboard and screen-reader tested, dark mode, and installable on a phone."
- "Focused, explainable, and every assumption is on one page."

**Timing:** 20 + 40 + 60 + 40 + 40 + 50 + 20 + 30 s = 5:00 exactly. If running long, cut the heatmap/tilt aside in step 3 and the Spanish switch in step 6 first.

---

**If something breaks:** network down → local `make api` works offline (chat uses its deterministic reply). App down → play the backup video from step 2. Bedrock down → chat falls back automatically. Say so: "that's the fallback working."
