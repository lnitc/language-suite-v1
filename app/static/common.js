"use strict";
// Helpers shared by all features.

const $ = (id) => document.getElementById(id);

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

async function errorFrom(response) {
  const data = await response.json().catch(() => ({}));
  return new Error(typeof data.detail === "string" ? data.detail : "Something went wrong.");
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch {
    throw new Error("Could not reach the app server. Is it still running?");
  }
  if (!response.ok) throw await errorFrom(response);
  return response;
}

async function api(path, options) {
  return (await request(path, options)).json();
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read the uploaded file."));
    reader.readAsText(file);
  });
}

// Feature tabs
document.querySelectorAll(".tab[data-feature]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab[data-feature]").forEach((other) => {
      other.classList.toggle("active", other === tab);
    });
    document.querySelectorAll(".feature").forEach((feature) => {
      feature.hidden = feature.id !== `feature-${tab.dataset.feature}`;
    });
    showError("");
    document.dispatchEvent(new CustomEvent("feature-change"));
  });
});

api("/api/health")
  .then((info) => {
    $("model-info").textContent =
      `Model: ${info.llm_model} at ${info.llm_base_url} · Speech: ${info.tts_provider}`;
  })
  .catch(() => {});
