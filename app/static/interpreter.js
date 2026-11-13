"use strict";
// Feature 3: interpreter simulation. Uses common.js and voice.js.

(() => {
  const views = { setup: $("interp-setup"), live: $("interp-live"), results: $("interp-results") };

  let sessionId = null;
  let batches = [];
  let codes = { source: "", target: "" };
  let index = 0;
  let spoken = [];
  let heard = [];
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function status(text) { $("interp-status").textContent = text; }

  async function playBatch() {
    showError("");
    mic.setEnabled(false);
    status("Listen…");
    try {
      await voice.speak(batches[index], codes.source, Number($("interp-speed").value));
      heard[index] = true;
    } catch (error) {
      showError(error.message);
    }
    if (!sessionId) return;
    $("interp-play").textContent = "↻ Repeat";
    mic.setEnabled(true);
    status("Now interpret: press the microphone, speak, then press it again.");
  }

  function showBatch() {
    voice.stop();
    $("interp-progress").textContent = `Part ${index + 1} of ${batches.length}`;
    $("interp-play").textContent = heard[index] ? "↻ Repeat" : "▶ Play";
    $("interp-said").textContent = spoken[index] || "";
    $("interp-said-box").hidden = !spoken[index];
    $("interp-next").textContent = index === batches.length - 1 ? "Finish and get feedback" : "Next part →";
    mic.setEnabled(Boolean(heard[index]));
    status(heard[index] ? "Record again, or go on." : "Press Play to hear this part.");
  }

  const mic = voice.attachMic($("interp-mic"), {
    language: () => codes.target,
    onText: async (text) => {
      spoken[index] = text;
      $("interp-said").textContent = text;
      $("interp-said-box").hidden = false;
      status("Recorded. You can record again, or go on.");
    },
  });

  function block(label, text, className) {
    const line = document.createElement("p");
    const title = document.createElement("span");
    title.className = "muted";
    title.textContent = `${label} `;
    line.append(title, text || "-");
    if (className) line.className = className;
    return line;
  }

  function renderResults(result) {
    $("interp-overall").textContent = result.overall || "No overall comment was returned.";
    const container = $("interp-batches");
    container.replaceChildren();
    for (const row of result.batches) {
      const box = document.createElement("div");
      box.className = "sentence";
      const heading = document.createElement("p");
      heading.className = "muted";
      heading.textContent = `Part ${row.number}`;
      box.append(
        heading,
        block(`Original (${result.source_language}):`, row.original),
        block("You said:", row.interpretation || "(nothing said)"),
        block("Ideal version:", row.ideal, "ideal"),
        block("Comment:", row.comment)
      );
      container.appendChild(box);
    }
  }

  $("interp-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("interp-start");
    button.disabled = true;
    button.textContent = "Writing the text…";
    try {
      const started = await api("/api/interpreter/sessions", {
        method: "POST",
        body: JSON.stringify({
          source_language: $("interp-source").value.trim(),
          target_language: $("interp-target").value.trim(),
          difficulty: $("interp-difficulty").value,
          sentences_per_batch: Number($("interp-per-batch").value),
          batch_count: Number($("interp-batch-count").value),
          system_prompt: $("interp-system-prompt").value,
          session_prompt: $("interp-session-prompt").value,
        }),
      });
      sessionId = started.session_id;
      batches = started.batches;
      codes = { source: started.source_language_code, target: started.target_language_code };
      index = 0;
      spoken = new Array(batches.length).fill("");
      heard = new Array(batches.length).fill(false);
      voice.fillSelect($("interp-voice"), $("interp-voice-label"), codes.source);
      show("live");
      showBatch();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  $("interp-play").addEventListener("click", playBatch);

  $("interp-next").addEventListener("click", async () => {
    showError("");
    await mic.reset();
    if (index < batches.length - 1) {
      index += 1;
      showBatch();
      return;
    }
    voice.stop();
    setBusy(views.live, "Writing your feedback…");
    try {
      const result = await api(`/api/interpreter/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ interpretations: spoken }),
      });
      finished = { result, date: new Date() };
      renderResults(result);
      show("results");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.live, null);
    }
  });

  // Saves the result as a plain text file: for every part the original, the
  // learner's interpretation, the ideal version and the comment.
  $("interp-download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Interpreter simulation",
      `Languages: ${result.source_language} -> ${result.target_language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      "",
      "===== FEEDBACK =====",
      "",
      result.overall || "(No overall comment was returned.)",
      "",
      "===== PART BY PART =====",
    ];
    for (const row of result.batches) {
      lines.push(
        "",
        `Part ${row.number}`,
        `Original (${result.source_language}): ${row.original}`,
        `You said: ${row.interpretation || "(nothing said)"}`,
        `Ideal version: ${row.ideal || "-"}`,
        `Comment: ${row.comment || "-"}`
      );
    }
    lines.push("");
    downloadTextFile("interpreter", date, lines);
  });

  $("interp-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  document.addEventListener("feature-change", () => {
    if (sessionId && !views.live.hidden) { voice.stop(); mic.reset(); }
  });
})();
