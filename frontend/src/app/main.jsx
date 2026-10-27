// Phone app entry point (loaded by app.html): mounts <PhoneApp/> with the shared styles, then the app's own layout.
import React from "react";
import { createRoot } from "react-dom/client";
import PhoneApp from "./PhoneApp.jsx";
import "../styles.css";
import "./app.css";
createRoot(document.getElementById("root")).render(<PhoneApp />);

// Same service worker as the web app (production builds only; never caches /api).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
