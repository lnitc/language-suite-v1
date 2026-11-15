"use strict";
// Helpers shared by all features.

const $ = (id) => document.getElementById(id);

function showError(message) {
  $("error").textContent = message || "";
  $("error").hidden = !message;
}

// A note from the app that is not an error, such as "this request is large
// for the model". It stays until it is closed or another feature is opened.
function showWarning(message) {
  $("warning-text").textContent = message || "";
  $("warning").hidden = !message;
}

// ---------- settings: remembered in this browser, used by every feature ----------

const appSettings = { learning: "", native: "", level: "", feedback: "" };
try {
  Object.assign(appSettings, JSON.parse(localStorage.getItem("language-suite-settings") || "{}"));
} catch { /* no saved settings, or storage is unavailable */ }

// The language for the teacher's feedback: the chosen one, else the learner's own.
function feedbackLanguage() {
  return (appSettings.feedback || appSettings.native || "").trim();
}

// Which form fields each setting fills in.
const SETTING_FIELDS = [
  ["talk-language", "learning"], ["dict-language", "learning"], ["essay-language", "learning"],
  ["read-language", "learning"], ["listen-language", "learning"], ["shadow-language", "learning"], ["wl-source", "learning"], ["wl-target", "native"],
  ["interp-source", "learning"], ["interp-target", "native"],
  ["source-language", "native"], ["target-language", "learning"],        // vocabulary: shown in my language, answered in the new one
  ["tr-source-language", "native"], ["tr-target-language", "learning"],  // translation: into the language being learned
  ["talk-difficulty", "level"], ["dict-difficulty", "level"], ["essay-difficulty", "level"],
  ["read-difficulty", "level"], ["listen-difficulty", "level"], ["shadow-difficulty", "level"], ["interp-difficulty", "level"], ["wl-difficulty", "level"], ["tr-difficulty", "level"],
];

// Fills in fields the learner has not touched: empty ones, and ones that
// still hold a value this function put there earlier.
function applySettings() {
  for (const [id, key] of SETTING_FIELDS) {
    const field = $(id);
    const value = appSettings[key];
    if (!field || !value) continue;
    const isSelect = field.tagName === "SELECT";
    if (isSelect && ![...field.options].some((option) => option.value === value)) continue;
    const untouched = isSelect ? field.dataset.auto === undefined : field.value === "";
    if (untouched || field.value === field.dataset.auto) {
      field.value = value;
      field.dataset.auto = value;
    }
  }
}

async function errorFrom(response) {
  const data = await response.json().catch(() => ({}));
  return new Error(typeof data.detail === "string" ? data.detail : "Something went wrong.");
}

async function request(path, options = {}) {
  let response;
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  // Header values must be plain ASCII, so the language name is encoded.
  if (feedbackLanguage()) headers["X-Feedback-Language"] = encodeURIComponent(feedbackLanguage());
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("Could not reach the app server. Is it still running?");
  }
  if (!response.ok) throw await errorFrom(response);
  const warning = response.headers.get("X-App-Warning");
  if (warning) showWarning(decodeURIComponent(warning));
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
async function readMaterial(file, { allowImages = false, warnWhenLong = true } = {}) {
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

  const note = warnWhenLong && text.length > MATERIAL_LIMIT
    ? `"${file.name}" is long (${text.length.toLocaleString()} characters): only the first ` +
      `${MATERIAL_LIMIT.toLocaleString()} are used. Put the most important part at the top, or upload a shorter file.`
    : "";
  return { ...empty, text: text.slice(0, 200000), note };
}

// Saves lines of text as a .txt file in the Downloads folder. The file is
// built in the browser from what is on screen; nothing is sent anywhere.
// Returns nothing; `prefix` and `date` make a name like "dictation-2026-11-13-1013.txt".
function downloadTextFile(prefix, date, lines, extension = "txt", type = "text/plain", marker = true) {
  // Windows line endings, and (unless switched off) a UTF-8 marker so Notepad
  // and Excel show every script correctly.
  const text = (marker ? "\uFEFF" : "") + lines.join("\n").replace(/\r?\n/g, "\r\n");
  downloadBlob(new Blob([text], { type: `${type};charset=utf-8` }), fileName(prefix, date, extension));
}

// "wordlist", a date and "csv" -> "wordlist-2026-11-14-0944.csv"
function fileName(prefix, date, extension) {
  const stamp = dateStamp(date);
  return `${prefix}-${stamp.day}-${stamp.time.replace(":", "")}${extension ? `.${extension}` : ""}`;
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
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

// Shrinks a photo in the browser before upload: phone photos are far larger
// than a model needs, and a smaller image is read faster. Returns a JPEG data URL.
async function photoToDataUrl(file, longestSide = 1600) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error(`"${file.name}" could not be opened as an image. Use a PNG, JPEG or WebP file.`);
  }
  const scale = Math.min(1, longestSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff"; // transparent PNGs get a white page
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

// Covers a section with a spinner and a message while the app waits for the
// model, and locks its buttons and fields. Call with no message to remove it.
function setBusy(section, message) {
  let overlay = section.querySelector(":scope > .busy");
  if (!message) {
    if (overlay) overlay.remove();
    section.inert = false;
    return;
  }
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "busy";
    overlay.setAttribute("role", "status");
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    overlay.append(spinner, document.createElement("span"));
    section.appendChild(overlay);
  }
  overlay.lastChild.textContent = message;
  section.inert = true; // no clicks or typing underneath
}

function showNote(id, message) {
  $(id).textContent = message || "";
  $(id).hidden = !message;
}

// Navigation: sections (Speaking, Vocabulary, Writing, Reading) on top, and
// below them the features of the chosen section.
const sectionTabs = [...document.querySelectorAll(".section-tab")];
const featureTabs = [...document.querySelectorAll(".tab[data-feature]")];
const lastOpened = {}; // section -> the feature tab last used there

function openFeature(tab) {
  featureTabs.forEach((other) => other.classList.toggle("active", other === tab));
  document.querySelectorAll(".feature").forEach((feature) => {
    feature.hidden = feature.id !== `feature-${tab.dataset.feature}`;
  });
  lastOpened[tab.dataset.section] = tab;
  showError("");
  showWarning("");
  setTimeout(applySettings, 0); // after the feature has rebuilt its own form
  document.dispatchEvent(new CustomEvent("feature-change", { detail: { ...tab.dataset } }));
}

function openSection(name) {
  sectionTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.section === name));
  const mine = featureTabs.filter((tab) => tab.dataset.section === name);
  featureTabs.forEach((tab) => { tab.hidden = tab.dataset.section !== name; });
  $("feature-nav").hidden = mine.length < 2; // one feature: no second row needed
  openFeature(lastOpened[name] || mine[0]);
}

featureTabs.forEach((tab) => tab.addEventListener("click", () => openFeature(tab)));
sectionTabs.forEach((tab) => tab.addEventListener("click", () => openSection(tab.dataset.section)));

api("/api/health")
  .then((info) => {
    $("model-info").textContent =
      `Model: ${info.llm_model} at ${info.llm_base_url} · Voice: ${info.tts_provider} · Microphone: ${info.stt_provider}`;
  })
  .catch(() => {});

// ---------- settings panel ----------

function toggleSettings(open) {
  $("settings-panel").hidden = !open;
  $("settings-open").setAttribute("aria-expanded", String(open));
  if (open) {
    $("set-learning").value = appSettings.learning;
    $("set-native").value = appSettings.native;
    $("set-level").value = appSettings.level;
    $("set-feedback").value = appSettings.feedback;
    $("settings-saved").hidden = true;
  }
}

$("settings-open").addEventListener("click", () => toggleSettings($("settings-panel").hidden));
$("settings-close").addEventListener("click", () => toggleSettings(false));
$("warning-close").addEventListener("click", () => showWarning(""));

$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  appSettings.learning = $("set-learning").value.trim();
  appSettings.native = $("set-native").value.trim();
  appSettings.level = $("set-level").value;
  appSettings.feedback = $("set-feedback").value.trim();
  try {
    localStorage.setItem("language-suite-settings", JSON.stringify(appSettings));
  } catch { /* the settings still apply until the page is closed */ }
  applySettings();
  document.dispatchEvent(new CustomEvent("settings-change"));
  $("settings-saved").hidden = false;
});

window.addEventListener("load", applySettings);
