"use strict";
// Feature 12: speech (public speaking). Uses helpers from common.js and voice.js.

(() => {
  const views = { setup: $("sp-setup"), write: $("sp-write"), results: $("sp-results") };
  const HINTS = {
    assignment: ["(optional: kind of speech, occasion, audience)", "e.g. A short talk to new colleagues about teamwork", "Get an assignment"],
    own: ["(your topic, and who you are speaking to)", "e.g. A two-minute self-introduction at a conference", "Continue"],
  };

  let sessionId = null;
  let languageCode = "";
  let times = { target: 120, max: 180 };
  let seconds = 0;        // length of the last recording
  let startedAt = 0;
  let ticker = null;
  let audioUrl = null;
  let finished = null;    // the last result, for the download
  let sampleRun = 0;      // raised to stop the sample being read out
  let samplePlaying = false;

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  const clock = (total) => `${Math.floor(total / 60)}:${String(Math.round(total) % 60).padStart(2, "0")}`;
  function status(text) { $("sp-status").textContent = text; }

  function applyMode() {
    const [hint, placeholder, button] = HINTS[$("sp-mode").value];
    $("sp-session-hint").textContent = hint;
    $("sp-session-prompt").placeholder = placeholder;
    $("sp-start").textContent = button;
  }

  function showTimer(elapsed) {
    $("sp-timer").textContent = `${clock(elapsed)} / ${clock(times.target)}`;
    $("sp-timer").classList.toggle("over", elapsed > times.target);
  }

  const recorder = voice.attachMic($("sp-record"), {
    labels: { idle: "● Start recording", recording: "■ Stop recording", busy: "Writing down your speech…" },
    language: () => languageCode,
    maxMs: () => times.max * 1000,
    onState: (state) => {
      clearInterval(ticker);
      if (state === "recording") {
        startedAt = Date.now();
        showTimer(0);
        ticker = setInterval(() => showTimer((Date.now() - startedAt) / 1000), 250);
        status(`Recording. Aim for about ${clock(times.target)}; it stops by itself at ${clock(times.max)}.`);
      } else if (state === "busy") {
        seconds = Math.round((Date.now() - startedAt) / 1000);
        showTimer(seconds);
        status("Writing down what you said. A long speech takes a little while…");
      }
    },
    onRecording: (blob) => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      audioUrl = URL.createObjectURL(blob);
      $("sp-audio").src = audioUrl;
    },
    onText: async (text) => {
      $("sp-transcript").value = text;
      $("sp-form").hidden = false;
      $("sp-submit").hidden = false;
      status(
        seconds >= times.max
          ? `The recording was stopped at ${clock(times.max)}. Check the text below, then send it.`
          : "Check the text below, then send it. Or record again."
      );
    },
  });

  async function startSession() {
    const started = await api("/api/speaking/sessions", {
      method: "POST",
      body: JSON.stringify({
        language: $("sp-language").value.trim(),
        difficulty: $("sp-difficulty").value,
        minutes: Number($("sp-minutes").value),
        system_prompt: $("sp-system-prompt").value,
        session_prompt: $("sp-session-prompt").value,
        with_assignment: $("sp-mode").value === "assignment",
      }),
    });
    sessionId = started.session_id;
    languageCode = started.language_code;
    times = { target: started.target_seconds, max: started.max_seconds };
    $("sp-assignment").textContent = started.assignment;
    $("sp-assignment-box").hidden = !started.assignment;
  }

  function clearRecording() {
    seconds = 0;
    $("sp-transcript").value = "";
    $("sp-form").hidden = true;
    $("sp-submit").hidden = true;
    showTimer(0);
    status("Press the button when you are ready to speak.");
  }

  $("sp-mode").addEventListener("change", applyMode);

  $("sp-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("sp-start");
    button.disabled = true;
    if ($("sp-mode").value === "assignment") button.textContent = "Writing your assignment…";
    try {
      await startSession();
      await recorder.reset();
      clearRecording();
      show("write");
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      applyMode();
    }
  });

  $("sp-another").addEventListener("click", async () => {
    showError("");
    await recorder.reset();
    setBusy(views.write, "Writing another assignment…");
    try {
      await startSession();
      clearRecording(); // a speech on the old assignment would not fit the new one
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.write, null);
    }
  });

  $("sp-back").addEventListener("click", async () => {
    await recorder.reset();
    showError("");
    show("setup");
  });

  // ---------- results ----------

  const rating = (score) => (score === null ? "not rated" : `${score} / 5`);

  function timingLine(result) {
    const length = `Length: ${clock(result.seconds)} of about ${clock(result.target_seconds)}`;
    const speed = result.pace.per_minute === null
      ? ""
      : ` · Pace: about ${result.pace.per_minute} ${result.pace.unit} per minute`;
    return `${length}${speed}. Measured by the app; the coach did not hear your voice.`;
  }

  function stopSample() {
    sampleRun += 1;
    samplePlaying = false;
    voice.stop();
    $("sp-listen").textContent = "🔊 Listen to the sample";
  }

  async function playSample() {
    const run = ++sampleRun;
    const parts = finished.result.sample
      .split(/\n+/)
      .flatMap((paragraph) => paragraph.split(/(?<=[.!?…])\s+|(?<=[。！？])(?![」』）。！？])/))
      .map((sentence) => sentence.trim())
      .filter(Boolean);
    samplePlaying = true;
    $("sp-listen").textContent = "■ Stop";
    try {
      for (let i = 0; i < parts.length && run === sampleRun; i += 1) {
        await voice.speak(parts[i], finished.result.language_code, Number($("sp-speed").value));
      }
    } catch (error) {
      showError(error.message);
    }
    if (run === sampleRun) stopSample();
  }

  function renderResults(result) {
    $("sp-rating").textContent = result.max_total
      ? `Rating: ${result.total} / ${result.max_total}`
      : "Rating: not available";
    $("sp-timing").textContent = timingLine(result);
    const scores = $("sp-scores");
    scores.replaceChildren();
    for (const row of result.scores) {
      const tr = scores.insertRow();
      for (const text of [row.name, rating(row.score), row.comment]) {
        tr.insertCell().textContent = text; // textContent: model output is never run as HTML
      }
    }
    $("sp-feedback").textContent = result.feedback;
    const list = $("sp-corrections");
    list.replaceChildren();
    $("sp-corrections-title").hidden = result.corrections.length === 0;
    for (const item of result.corrections) {
      const box = document.createElement("div");
      box.className = "correction";
      for (const [className, text] of [["was", item.original], ["now", item.better], ["muted", item.explanation]]) {
        if (!text) continue;
        const p = document.createElement("p");
        p.className = className;
        p.textContent = text;
        box.appendChild(p);
      }
      list.appendChild(box);
    }
    $("sp-sample").textContent = result.sample;
    $("sp-own").textContent = result.transcript;
    voice.fillSelect($("sp-voice"), $("sp-voice-label"), result.language_code);
  }

  $("sp-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    if ($("sp-transcript").value.trim().length < 10) {
      showError("There is too little speech to review. Please record a longer speech.");
      return;
    }
    $("sp-audio").pause();
    setBusy(views.write, "Reviewing your speech… This can take a minute or two.");
    try {
      const result = await api(`/api/speaking/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ transcript: $("sp-transcript").value, seconds }),
      });
      finished = { result, date: new Date() };
      saveToHistory({
        feature: "speech",
        language: result.language,
        title: (result.assignment || "").split("\n")[0],
        score: result.max_total ? result.total : null,
        total: result.max_total || null,
        lines: report(),
        mistakes: result.corrections.map((item) => ({
          prompt: item.original,
          correct: item.better,
          note: item.explanation || "",
        })),
      });
      renderResults(result);
      show("results");
      window.scrollTo(0, 0);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.write, null);
    }
  });

  $("sp-listen").addEventListener("click", () => (samplePlaying ? stopSample() : playSample()));

  // Same assignment, new recording.
  $("sp-again").addEventListener("click", () => {
    stopSample();
    showError("");
    clearRecording();
    show("write");
  });

  $("sp-restart").addEventListener("click", () => {
    stopSample();
    sessionId = null;
    showError("");
    show("setup");
  });

  // The result as lines of text: for the download and for the history.
  function report() {
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Speech (public speaking)",
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      result.max_total ? `Rating: ${result.total} / ${result.max_total}` : "Rating: not available",
      ...result.scores.map((row) => `  ${row.name}: ${rating(row.score)}${row.comment ? ` - ${row.comment}` : ""}`),
      timingLine(result),
      "",
    ];
    if (result.assignment) lines.push("===== ASSIGNMENT =====", "", result.assignment, "");
    lines.push("===== YOUR SPEECH (as heard by the app) =====", "", result.transcript, "");
    lines.push("===== FEEDBACK =====", "", result.feedback, "");
    if (result.corrections.length) {
      lines.push("===== CORRECTIONS =====");
      result.corrections.forEach((item, i) => {
        lines.push("", `${i + 1}. You said: ${item.original}`, `   Better:   ${item.better}`);
        if (item.explanation) lines.push(`   Why:      ${item.explanation}`);
      });
      lines.push("");
    }
    lines.push("===== SAMPLE SCRIPT OF AN IDEAL SPEECH =====", "", result.sample, "");
    return lines;
  }

  $("sp-download").addEventListener("click", () => {
    if (finished) downloadTextFile("speech", finished.date, report());
  });

  document.addEventListener("feature-change", () => {
    if (samplePlaying) stopSample();
    if (sessionId && !views.write.hidden) recorder.reset();
  });

  applyMode();
})();
