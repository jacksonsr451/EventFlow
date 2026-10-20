import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@eventflow/ui/styles.css";
import "./styles/global.css";
import { App } from "./app";

const root = document.getElementById("root");

if (!root) {
  throw new Error("EventFlow root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
