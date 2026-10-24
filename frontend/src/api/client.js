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
