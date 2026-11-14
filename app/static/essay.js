"use strict";
// Feature 7: essay writing. Uses helpers from common.js.

(() => {
  const views = { setup: $("essay-setup"), write: $("essay-write"), results: $("essay-results") };
  const HINTS = {
    assignment: ["(optional: topic or kind of essay)", "e.g. An opinion essay about life in a big city", "Get an assignment"],
    own: ["(optional: what your essay is about, or the task you were given)", "e.g. A letter of complaint to a hotel, for my writing class", "Continue"],
  };

  let sessionId = null;
  let limits = { recommended: 2000, max: 5000 };
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function applyMode() {
    const [hint, placeholder, button] = HINTS[$("essay-mode").value];
    $("essay-session-hint").textContent = hint;
    $("essay-session-prompt").placeholder = placeholder;
    $("essay-start").textContent = button;
  }

  // Counts the characters and warns when the essay is long.
  function updateCount() {
    const length = $("essay-text").value.trim().length;
    const number = (n) => n.toLocaleString();
    $("essay-count").textContent =
      `${number(length)} characters (recommended: up to ${number(limits.recommended)})`;
    let warning = "";
    if (length > limits.max) {
      warning = `Your essay is longer than ${number(limits.max)} characters, the most this app can ` +
        "review at once. Please shorten it, or check it in two parts.";
    } else if (length > limits.recommended) {
      warning = `Your essay is longer than the recommended ${number(limits.recommended)} characters. ` +
        "You can still send it, but a small local model will take longer and may review the end less carefully.";
    }
    showNote("essay-long-note", warning);
    $("essay-submit").disabled = length > limits.max;
  }

  async function startSession() {
    const started = await api("/api/essay/sessions", {
      method: "POST",
      body: JSON.stringify({
        language: $("essay-language").value.trim(),
        difficulty: $("essay-difficulty").value,
        system_prompt: $("essay-system-prompt").value,
        session_prompt: $("essay-session-prompt").value,
        with_assignment: $("essay-mode").value === "assignment",
      }),
    });
    sessionId = started.session_id;
    limits = { recommended: started.recommended_chars, max: started.max_chars };
    $("essay-assignment").textContent = started.assignment;
    $("essay-assignment-box").hidden = !started.assignment;
    updateCount();
  }

  $("essay-mode").addEventListener("change", applyMode);

  $("essay-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("essay-start");
    button.disabled = true;
    if ($("essay-mode").value === "assignment") button.textContent = "Writing your assignment…";
    try {
      await startSession();
      $("essay-text").value = "";
      $("essay-files").value = "";
      showNote("essay-upload-note", "");
      updateCount();
      show("write");
      $("essay-text").focus();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      applyMode();
    }
  });

  $("essay-another").addEventListener("click", async () => {
    showError("");
    setBusy(views.write, "Writing another assignment…");
    try {
      await startSession(); // what is already typed stays in the box
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.write, null);
    }
  });

  $("essay-text").addEventListener("input", updateCount);

  // Uploads end up in the text box, so the learner always sees and can fix
  // what will be marked: a document's text, or handwriting read from photos.
  $("essay-files").addEventListener("change", async () => {
    const files = [...$("essay-files").files];
    if (!files.length) return;
    showError("");
    showNote("essay-upload-note", "");
    const photos = files.filter((file) => file.type.startsWith("image/"));
    try {
      if (photos.length && photos.length !== files.length) {
        throw new Error("Please choose either photos of handwriting or one document, not both.");
      }
      if (photos.length > 4) throw new Error("Please choose at most four photos.");
      if (!photos.length && files.length > 1) throw new Error("Please choose one document at a time.");

      if (photos.length) {
        setBusy(views.write, "Reading your handwriting…");
        const images = [];
        for (const photo of photos) images.push(await photoToDataUrl(photo));
        const read = await api(`/api/essay/sessions/${sessionId}/handwriting`, {
          method: "POST",
          body: JSON.stringify({ images }),
        });
        $("essay-text").value = read.text;
        showNote(
          "essay-upload-note",
          "This is how the app read your handwriting. Compare it with your page before you send it: " +
          "where the app misread your writing, change it to what you really wrote, but leave your own " +
          "mistakes as they are. [?] marks a word the app could not read."
        );
      } else {
        setBusy(views.write, "Reading your file…");
        const { text } = await readMaterial(files[0], { warnWhenLong: false });
        if (!text.trim()) throw new Error("No text was found in that file.");
        $("essay-text").value = text.trim();
        showNote("essay-upload-note", `The text of "${files[0].name}" is now in the box. Check it before you send it.`);
      }
      updateCount();
    } catch (error) {
      showError(error.message);
      $("essay-files").value = "";
    } finally {
      setBusy(views.write, null);
    }
  });

  $("essay-back").addEventListener("click", () => {
    showError("");
    show("setup");
  });

  // ---------- results ----------

  const rating = (score) => (score === null ? "not rated" : `${score} / 5`);

  function renderResults(result) {
    $("essay-rating").textContent = result.max_total
      ? `Rating: ${result.total} / ${result.max_total}`
      : "Rating: not available";
    const scores = $("essay-scores");
    scores.replaceChildren();
    for (const row of result.scores) {
      const tr = scores.insertRow();
      for (const text of [row.name, rating(row.score), row.comment]) {
        tr.insertCell().textContent = text; // textContent: model output is never run as HTML
      }
    }
    $("essay-feedback").textContent = result.feedback;

    const list = $("essay-corrections");
    list.replaceChildren();
    $("essay-corrections-title").hidden = result.corrections.length === 0;
    for (const item of result.corrections) {
      const box = document.createElement("div");
      box.className = "correction";
      const was = document.createElement("p");
      was.className = "was";
      was.textContent = item.original;
      const now = document.createElement("p");
      now.className = "now";
      now.textContent = item.corrected;
      const why = document.createElement("p");
      why.className = "muted";
      why.textContent = item.explanation;
      box.append(was, now, why);
      list.appendChild(box);
    }
    $("essay-ideal").textContent = result.ideal;
    $("essay-own").textContent = result.essay;
  }

  $("essay-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    if ($("essay-text").value.trim().length < 20) {
      showError("The essay is too short to review. Please write a little more.");
      return;
    }
    setBusy(views.write, "Reading and rating your essay… This can take a minute or two.");
    try {
      const result = await api(`/api/essay/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ text: $("essay-text").value }),
      });
      finished = { result, date: new Date() };
      renderResults(result);
      show("results");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.write, null);
    }
  });

  $("essay-edit").addEventListener("click", () => {
    showError("");
    show("write");
    $("essay-text").focus();
  });

  $("essay-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // Saves everything as a plain text file.
  $("essay-download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Essay writing",
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      result.max_total ? `Rating: ${result.total} / ${result.max_total}` : "Rating: not available",
      ...result.scores.map((row) => `  ${row.name}: ${rating(row.score)}${row.comment ? ` - ${row.comment}` : ""}`),
      "",
    ];
    if (result.assignment) lines.push("===== ASSIGNMENT =====", "", result.assignment, "");
    lines.push("===== YOUR ESSAY =====", "", result.essay, "");
    lines.push("===== FEEDBACK =====", "", result.feedback, "");
    if (result.corrections.length) {
      lines.push("===== CORRECTIONS =====");
      result.corrections.forEach((item, i) => {
        lines.push("", `${i + 1}. You wrote: ${item.original}`, `   Better:    ${item.corrected}`);
        if (item.explanation) lines.push(`   Why:       ${item.explanation}`);
      });
      lines.push("");
    }
    lines.push("===== IDEAL VERSION =====", "", result.ideal, "");
    downloadTextFile("essay", date, lines);
  });

  applyMode();
})();
