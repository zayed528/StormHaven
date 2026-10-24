# StormHaven demo script

**Owner:** Abby (script). **Presenter:** Akshat. Target: **5 minutes**, then Q&A. Rehearse at least 3 times (hours 20–24).
Each step names the minimum-viable-demo (MVD) step it proves. The judges' rule "change at least one scenario input and see the response change" is covered in step 3.

**Setup before going on stage**
- `make api` + `make web` on the demo laptop, **and** a deployed URL as backup, **and** the backup video (recorded by hour 22).
- Browser zoom 110%. Close other tabs. Phone with SNS sandbox number on the table, volume on.
- Reset the scenario: severity 97 (the default), crews 20, roads normal, no damage, no needs, alerts on, demo toggle off.
- Know the demo premise IDs (real data): one High dot in the southern circuits and one Low. Write them on a card; don't show premise IDs on slides.
- Severity on real data is the storm's rank among 36 recorded ARCOS storms. 97 ≈ a serious storm; 99 ≈ the Feb 2025 storm. Below about 90 everything is calm, which is honest but dull, so stay in the 95–99 range on stage.

---

### 1. Pick a location (MVD 1) ~20 s
> "A storm is 36 hours out. Maria wants to know what it means for *her* home."
- Click a red or orange dot (each dot = one neighborhood transformer and its homes), or type the premise ID in "Or enter your premise ID".
- Point out: anonymized IDs only; the map shows risk bands, never hospitals or fire stations.

### 2. "Will I lose power?" (MVD 2) ~40 s
- Read the band and confidence aloud: "**High outage risk, Medium confidence**."
- Point to **Why**: equipment history on *her* line, storm strength, path exposure.
- Open **Assumptions, missing data, and limits** for 3 seconds: "every number traces back to `assumptions.yaml`."

### 3. Explore scenarios → restoration range (MVD 3) ~60 s, **judges' interaction**
- Read the range: "If you lose power, most likely X to Y hours. **A range, not a promise**."
- Drag **storm strength** from 97 to 99 → the label under the slider changes to "Similar to the Feb 2025 storm: gusts up to 63 mph…", the map reddens, and the band and range move. Say: "The scale is our own storm history, labeled with the real weather of each storm."
- Set **road access → Blocked** → range widens; the driver text explains why.
- Set **Damage reported → Broken pole** → range jumps. "Pole replacement hours come from AEP's labor sheet, plus travel and setup time."
- Point at the **step timeline**: the main line is fixed first, so ETAs never go backwards. That's step restoration.
- **Offer a judge the slider.**

### 4. Prepare + alert eligibility (MVD 4) ~40 s
- Show **What you can do**: actions change with risk and duration (water storage appears for day-plus outages).
- Tick **Powered medical equipment** (opt-in, never inferred) → medical battery and backup-plan items appear, a medical **Safety** item appears, and "**We'll follow up personally**" shows the human callback escalation.
- Read **Alerts**: eligible because she's enrolled and has a channel. Point at the rule text.

*(Optional, if real weather is happening on demo day: point at the live forecast card and any NWS warning. "This is today's real forecast for the area. It's context; you choose the scenario.")*

### 5. Proactive communication (MVD 5) ~40 s
- Show the **Before the storm** message.
- Tick **Demo only → Simulate: the utility confirms an outage**. The **Confirmed by AEP** column fills, labeled as utility data, still separate from **Our estimate**.
- Change crews → **Estimate updated** message shows old → new range *and the real reason* ("fewer repair crews are available").
- *(If SNS is live)* Nandan sends the pre-storm text; the phone buzzes.

### 6. Trust: privacy, safety, uncertainty, limits (MVD 6) ~50 s
- In chat: "**There's a downed wire sparking in my yard**" → the reply **starts with a fixed 911 safety message** (not LLM-written).
- In chat: "Where is the nearest hospital on my circuit?" → no location is revealed. Facility locations never leave the backend, so neither the API nor the LLM has them, and the system prompt tells Claude to decline. (Rehearse this with Bedrock on; offline mode just repeats the outlook.)
- Type a made-up premise ID → **fallback**: "We can't make a reliable prediction... check AEP's outage map." No made-up numbers.
- One line: "The LLM never computes a number. It calls our engines and explains. Every string is scrubbed for IDs, coordinates and contacts before it leaves the API."

### 7. Close: credibility + modernization ~30 s
- Backtest slide (from `05`): calibration and restoration-range coverage. If 05 didn't run on real data, show the synthetic-only caveat honestly.
- Architecture in one breath: AEP topology + ARCOS history + labor sheets → 4 deterministic engines → Claude on Bedrock with Guardrails explains → SNS alerts → audit trail.
- "Focused, explainable, and every assumption is on one page."

---

**If something breaks:** network down → local `make api` works offline (chat uses its deterministic reply). App down → play the backup video from step 2. Bedrock down → chat falls back automatically. Say so: "that's the fallback working."
