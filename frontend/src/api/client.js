
// All backend calls in one place. Shapes match backend/app/schemas.py.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const apiUrl = (path) => `${API_BASE}${path}`;

const post = (url, body, options = {}) =>
  fetch(apiUrl(url), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    ...options,
  }).then((r) => {
    if (!r.ok) throw new Error(`${url} failed: ${r.status}`);
    return r.json();
  });

// Health endpoint
export const getHealth = () =>
  fetch(apiUrl("/api/health")).then((r) => r.json());

// Cache maps by storm severity to avoid repeated downloads.
// Failed requests are removed from cache so they can be retried.
const maps = new Map();

export const getMap = (severity) => {
  if (!maps.has(severity)) {
    maps.set(
      severity,
      fetch(apiUrl(`/api/map?severity=${severity}`))
        .then((r) => {
          if (!r.ok) {
            throw new Error(`/api/map failed: ${r.status}`);
          }
          return r.json();
        })
        .catch((e) => {
          maps.delete(severity);
          throw e;
        })
    );
  }

  return maps.get(severity);
};

export const mapCached = (severity) => maps.has(severity);

// Concierge, weather, and chat endpoints
export const getConcierge = (req) => post("/api/concierge", req);

export const getWeather = () =>
  fetch(apiUrl("/api/weather")).then((r) => r.json());

export const sendChat = (req, options) =>
  post("/api/chat", req, options);

// Notification endpoint
// Use VITE_MOCK_NOTIFY=1 for local testing without sending notifications.
const MOCK_NOTIFY = import.meta.env.VITE_MOCK_NOTIFY === "1";

export const sendNotify = (req) =>
  MOCK_NOTIFY
    ? new Promise((ok) =>
        setTimeout(
          () =>
            ok({
              sent: false,
              dry_run: true,
              mock: true,
              text: null,
            }),
          500
        )
      )
    : post("/api/notify", req);
