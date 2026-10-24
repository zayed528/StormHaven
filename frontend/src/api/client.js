// All backend calls in one place. Shapes match backend/app/schemas.py (see docs/API_CONTRACT.md).
// POST JSON and throw on non-2xx, so callers can show one error message.
const post = (url, body) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => { if (!r.ok) throw new Error(`${url} failed: ${r.status}`); return r.json(); });

export const getHealth = () => fetch("/api/health").then((r) => r.json());
export const getMap = (severity) => fetch(`/api/map?severity=${severity}`).then((r) => {
  if (!r.ok) throw new Error(`/api/map failed: ${r.status}`); return r.json();
});
export const getConcierge = (req) => post("/api/concierge", req);
export const getWeather = () => fetch("/api/weather").then((r) => r.json());
export const sendChat = (req) => post("/api/chat", req);

// POST /api/notify (Jaid): {message_key, premise_id, scenario, profile} -> {sent, dry_run, text}.
// Until the endpoint exists, start the dev server with VITE_MOCK_NOTIFY=1 to get a fake reply (nothing is sent).
const MOCK_NOTIFY = import.meta.env.VITE_MOCK_NOTIFY === "1";
export const sendNotify = (req) => (MOCK_NOTIFY
  ? new Promise((ok) => setTimeout(() => ok({ sent: false, dry_run: true, mock: true, text: null }), 500))
  : post("/api/notify", req));
