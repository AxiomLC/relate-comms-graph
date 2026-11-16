import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import "./styles/globals.css";

/**
 * Entry point. Cytoscape and fcose are loaded as plain scripts by `index.html`
 * (vendored, not bundled) and arrive on `window` before this module runs.
 */
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
