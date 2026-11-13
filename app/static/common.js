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

function readFile(file, how) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read the uploaded file."));
    reader[how](file);
  });
}

// How much of a document the model is given. Longer material is cut off.
const MATERIAL_LIMIT = 8000;

// Turns an uploaded file into material for a session.
// Returns { text, image, note }: text for documents, a data URL for images,
// and a note to show the learner (for example when a long file was cut).
async function readMaterial(file, { allowImages = false } = {}) {
  const empty = { text: "", image: "", note: "" };
  if (!file) return empty;
  if (file.size > 20 * 1024 * 1024) {
    throw new Error("The file is larger than 20 MB. Please use a smaller one.");
  }
  const name = file.name.toLowerCase();

  if (file.type.startsWith("image/")) {
    if (!allowImages) throw new Error("Images cannot be used here. Use a text, PDF or Word file.");
    if (file.size > 5 * 1024 * 1024) {
      throw new Error("The image is larger than 5 MB. Please use a smaller one.");
    }
    return { ...empty, image: await readFile(file, "readAsDataURL") };
  }

  let text;
  if (/\.(pdf|docx|doc)$/.test(name) || file.type === "application/pdf") {
    // PDF and Word files are unpacked by the app server (on this computer).
    const response = await request(
      `/api/materials/extract?filename=${encodeURIComponent(file.name)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file }
    );
    text = (await response.json()).text;
  } else {
    text = await readFile(file, "readAsText");
  }

  const note = text.length > MATERIAL_LIMIT
    ? `"${file.name}" is long (${text.length.toLocaleString()} characters): only the first ` +
      `${MATERIAL_LIMIT.toLocaleString()} are used. Put the most important part at the top, or upload a shorter file.`
    : "";
  return { ...empty, text: text.slice(0, 200000), note };
}

// Saves lines of text as a .txt file in the Downloads folder. The file is
// built in the browser from what is on screen; nothing is sent anywhere.
// Returns nothing; `prefix` and `date` make a name like "dictation-2026-11-13-1013.txt".
function downloadTextFile(prefix, date, lines) {
  const stamp = dateStamp(date);
  // Windows line endings, and a UTF-8 marker so Notepad shows every script correctly.
  const text = "\uFEFF" + lines.join("\n").replace(/\r?\n/g, "\r\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${prefix}-${stamp.day}-${stamp.time.replace(":", "")}.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function dateStamp(date) {
  const two = (n) => String(n).padStart(2, "0");
  return {
    day: `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`,
    time: `${two(date.getHours())}:${two(date.getMinutes())}`,
  };
}

function showNote(id, message) {
  $(id).textContent = message || "";
  $(id).hidden = !message;
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
    document.dispatchEvent(new CustomEvent("feature-change", { detail: { ...tab.dataset } }));
  });
});

api("/api/health")
  .then((info) => {
    $("model-info").textContent =
      `Model: ${info.llm_model} at ${info.llm_base_url} · Voice: ${info.tts_provider} · Microphone: ${info.stt_provider}`;
  })
  .catch(() => {});
