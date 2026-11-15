"use strict";
// Feature 3: interpreter simulation. Uses common.js and voice.js.

(() => {
  const views = { setup: $("interp-setup"), live: $("interp-live"), results: $("interp-results") };

  let sessionId = null;
  let parts = []; // each: { text, from_language, to_language, speak_code, answer_code, speaker, role }
  let index = 0;
  let spoken = [];
  let heard = [];
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function status(text) { $("interp-status").textContent = text; }

  // "Speaker B (pharmacist)", or "" for a one-speaker speech.
  function who(part) {
    if (!part.speaker) return "";
    return `Speaker ${part.speaker}${part.role ? ` (${part.role})` : ""}`;
  }

  // The setup form changes its wording with the number of speakers.
  const WORDING = {
    1: ["You hear", "You interpret into", "Sentences before you interpret", "Number of parts",
        "e.g. A company president's speech about the new factory"],
    2: ["Speaker A speaks", "Speaker B speaks", "Sentences per turn", "Number of turns",
        "e.g. A tourist asks a pharmacist for advice"],
  };
  function applySpeakers() {
    const two = $("interp-speakers").value === "2";
    const [source, target, per, count, example] = WORDING[two ? 2 : 1];
    $("interp-source-label").textContent = source;
    $("interp-target-label").textContent = target;
    $("interp-per-label").textContent = per;
    $("interp-count-label").textContent = count;
    $("interp-session-prompt").placeholder = example;
    $("interp-dialogue-hint").hidden = !two;
  }

  async function playBatch() {
    showError("");
    mic.setEnabled(false);
    status("Listen…");
    try {
      await voice.speak(parts[index].text, parts[index].speak_code, Number($("interp-speed").value));
      heard[index] = true;
    } catch (error) {
      showError(error.message);
    }
    if (!sessionId) return;
    $("interp-play").textContent = "↻ Repeat";
    mic.setEnabled(true);
    status(`Now interpret into ${parts[index].to_language}: press the microphone, speak, then press it again.`);
  }

  function showBatch() {
    voice.stop();
    const part = parts[index];
    $("interp-progress").textContent = `${part.speaker ? "Turn" : "Part"} ${index + 1} of ${parts.length}`;
    // In a dialogue the direction changes with every turn, so it is shown large.
    const direction = $("interp-direction");
    direction.hidden = !part.speaker;
    if (part.speaker) {
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = "  →  ";
      direction.replaceChildren(`${who(part)} speaks ${part.from_language}`, arrow, `interpret into ${part.to_language}`);
    }
    voice.fillSelect($("interp-voice"), $("interp-voice-label"), part.speak_code); // voices of this turn's language
    $("interp-play").textContent = heard[index] ? "↻ Repeat" : "▶ Play";
    $("interp-said").textContent = spoken[index] || "";
    $("interp-said-box").hidden = !spoken[index];
    $("interp-next").textContent = index === parts.length - 1
      ? "Finish and get feedback"
      : part.speaker ? "Next turn →" : "Next part →";
    mic.setEnabled(Boolean(heard[index]));
    status(heard[index] ? "Record again, or go on." : `Press Play to hear this ${part.speaker ? "turn" : "part"}.`);
  }

  const mic = voice.attachMic($("interp-mic"), {
    language: () => parts[index].answer_code,
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

  // "Part 2" for a speech; "Turn 2 · Speaker B (pharmacist): Japanese → English" for a dialogue.
  function partTitle(row) {
    if (!row.speaker) return `Part ${row.number}`;
    return `Turn ${row.number} · ${who(row)}: ${row.from_language} → ${row.to_language}`;
  }

  function situation(session) {
    if (session.mode !== "dialogue") return "";
    const roles = session.roles || {};
    const people = ["A", "B"]
      .map((key) => `Speaker ${key}${roles[key] ? `: ${roles[key]}` : ""}`)
      .join(" · ");
    return `${session.setting ? `Situation: ${session.setting}. ` : ""}${people}`;
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
      heading.textContent = partTitle(row);
      box.append(
        heading,
        block(`Original (${row.from_language}):`, row.original),
        block(`You said (${row.to_language}):`, row.interpretation || "(nothing said)"),
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
    button.textContent = $("interp-speakers").value === "2" ? "Writing the dialogue…" : "Writing the text…";
    try {
      const started = await api("/api/interpreter/sessions", {
        method: "POST",
        body: JSON.stringify({
          speakers: Number($("interp-speakers").value),
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
      parts = started.parts;
      index = 0;
      spoken = new Array(parts.length).fill("");
      heard = new Array(parts.length).fill(false);
      showNote("interp-setting", situation(started));
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
    if (index < parts.length - 1) {
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
      result.mode === "dialogue"
        ? `Dialogue: Speaker A speaks ${result.source_language}, Speaker B speaks ${result.target_language}`
        : `Languages: ${result.source_language} -> ${result.target_language}`,
      ...(situation(result) ? [situation(result)] : []),
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
        partTitle(row).replace("→", "->"),
        `Original (${row.from_language}): ${row.original}`,
        `You said (${row.to_language}): ${row.interpretation || "(nothing said)"}`,
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

  $("interp-speakers").addEventListener("change", applySpeakers);
  applySpeakers();
})();
