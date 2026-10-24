// Browser entry point (loaded by index.html): mounts <App/> into #root and pulls in global styles.
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
createRoot(document.getElementById("root")).render(<App />);
