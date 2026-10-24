// Browser entry point (loaded by index.html): mounts <App/> into #root and pulls in global styles.
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
createRoot(document.getElementById("root")).render(<App />);

// Installable app (PWA): the service worker (public/sw.js) only in production builds, so `npm run dev` never
// serves stale files from a cache. It never caches /api answers. Failure is harmless: the app works without it.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
