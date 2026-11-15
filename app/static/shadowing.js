"use strict";
// Feature 11: shadowing (listen and repeat). Uses helpers from common.js and voice.js.

(() => {
  const views = { setup: $("shadow-setup"), live: $("shadow-live"), results: $("shadow-results") };

  let sessionId = null;
  let sentences = [];
  let languageCode = "";
  let index = 0;
  let attempts = []; // the last marking per sentence, or null
  let hideText = false;
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function status(text) { $("shadow-status").textContent = text; }

  // A line of words in which the ones that did not match are marked.
  function fillTokens(container, label, tokens, joiner, badClass) {
    container.replaceChildren();
    const title = document.createElement("span");
    title.className = "muted";
    title.textContent = `${label} `;
    container.appendChild(title);
    tokens.forEach((token, i) => {
      const span = document.createElement("span");
      span.textContent = token.text; // textContent: never run as HTML
      if (!token.ok) span.className = badClass;
      container.appendChild(span);
      if (joiner && i < tokens.length - 1) container.append(joiner);
    });
  }

  function showAttempt() {
    const attempt = attempts[index];
    $("shadow-attempt").hidden = !attempt;
    if (!attempt) return;
    $("shadow-score").textContent =
      `Recognised: ${attempt.percent}%` +
      (attempt.attempt > 1 ? ` (try ${attempt.attempt}; your best is ${attempt.best_percent}%)` : "");
    fillTokens($("shadow-marked"), "The sentence:", attempt.expected, attempt.joiner, "miss");
    fillTokens($("shadow-heard"), "The app heard:", attempt.heard, attempt.joiner, "extra");
  }

  function showSentence() {
    voice.stop();
    $("shadow-progress").textContent = `Sentence ${index + 1} of ${sentences.length}`;
    const hidden = hideText && !attempts[index];
    $("shadow-text").textContent = hidden ? "•  •  •" : sentences[index];
    $("shadow-play").textContent = "▶ Play";
    $("shadow-back").disabled = index === 0;
    $("shadow-next").textContent = index === sentences.length - 1 ? "Finish and see my result" : "Next sentence →";
    showAttempt();
    status(
      attempts[index]
        ? "Try again with the microphone, or go on."
        : hidden
          ? "Press Play to listen, then press the microphone and repeat what you heard."
          : "Press Play to listen, then press the microphone and say the sentence."
    );
  }

  async function play() {
    showError("");
    try {
      await voice.speak(sentences[index], languageCode, Number($("shadow-speed").value));
    } catch (error) {
      showError(error.message);
    }
    $("shadow-play").textContent = "↻ Repeat";
  }

  const mic = voice.attachMic($("shadow-mic"), {
    language: () => languageCode,
    onText: async (text) => {
      const at = index;
      const marked = await api(`/api/shadowing/sessions/${sessionId}/attempts`, {
        method: "POST",
        body: JSON.stringify({ index: at, text }),
      });
      attempts[at] = marked;
      if (at === index) showSentence(); // also reveals a hidden sentence
    },
  });

  async function begin(started) {
    sessionId = started.session_id;
    sentences = started.sentences;
    languageCode = started.language_code;
    index = 0;
    attempts = new Array(sentences.length).fill(null);
    voice.fillSelect($("shadow-voice"), $("shadow-voice-label"), languageCode);
    show("live");
    showSentence();
  }

  $("shadow-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("shadow-start");
    button.disabled = true;
    button.textContent = "Preparing the sentences…";
    try {
      const { text: material, note } = await readMaterial($("shadow-material").files[0]);
      showNote("shadow-note", note);
      hideText = $("shadow-hide").checked;
      await begin(await api("/api/shadowing/sessions", {
        method: "POST",
        body: JSON.stringify({
          language: $("shadow-language").value.trim(),
          difficulty: $("shadow-difficulty").value,
          count: Number($("shadow-count").value) || 5,
          system_prompt: $("shadow-system-prompt").value,
          session_prompt: $("shadow-session-prompt").value,
          material,
        }),
      }));
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  $("shadow-play").addEventListener("click", play);

  $("shadow-back").addEventListener("click", async () => {
    await mic.reset();
    if (index > 0) index -= 1;
    showSentence();
  });

  function renderResults(result) {
    $("shadow-average").textContent = result.average === null
      ? "You did not try any sentence."
      : `Recognised on average: ${result.average}% (best try of ${result.practised} of ${result.sentences.length} sentences)`;
    $("shadow-tips-title").hidden = !result.tips;
    $("shadow-tips").hidden = !result.tips;
    $("shadow-tips").textContent = result.tips;
    const rows = $("shadow-rows");
    rows.replaceChildren();
    for (const row of result.sentences) {
      const tr = rows.insertRow();
      const cells = [
        String(row.number),
        row.text,
        String(row.attempts),
        row.best_percent === null ? "-" : `${row.best_percent}%`,
        row.missed.join(", ") || (row.best_percent === null ? "-" : "nothing"),
      ];
      for (const text of cells) tr.insertCell().textContent = text;
    }
  }

  $("shadow-next").addEventListener("click", async () => {
    showError("");
    await mic.reset();
    if (index < sentences.length - 1) {
      index += 1;
      showSentence();
      return;
    }
    voice.stop();
    setBusy(views.live, "Preparing your result…");
    try {
      const result = await api(`/api/shadowing/sessions/${sessionId}/finish`, { method: "POST" });
      finished = { result, date: new Date() };
      renderResults(result);
      show("results");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.live, null);
    }
  });

  // The same sentences once more: earlier tries still count towards the best.
  $("shadow-again").addEventListener("click", () => {
    showError("");
    index = 0;
    show("live");
    showSentence();
  });

  $("shadow-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  $("shadow-download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Shadowing (listen and repeat)",
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      result.average === null ? "No sentence was tried." : `Recognised on average: ${result.average}%`,
      "This shows which words speech recognition could make out. It is not a pronunciation score.",
      "",
    ];
    if (result.tips) lines.push("===== COACH'S TIPS =====", "", result.tips, "");
    lines.push("===== SENTENCE BY SENTENCE =====");
    for (const row of result.sentences) {
      lines.push(
        "",
        `${row.number}. ${row.text}`,
        `   Tries: ${row.attempts}   Best: ${row.best_percent === null ? "-" : `${row.best_percent}%`}`
      );
      if (row.missed.length) lines.push(`   Not recognised: ${row.missed.join(", ")}`);
    }
    lines.push("");
    downloadTextFile("shadowing", date, lines);
  });

  document.addEventListener("feature-change", () => {
    if (sessionId && !views.live.hidden) { voice.stop(); mic.reset(); }
  });
})();
