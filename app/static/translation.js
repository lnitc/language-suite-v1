"use strict";
// Feature 9: written translation. Uses helpers from common.js.

(() => {
  const views = { setup: $("tr-setup"), write: $("tr-write"), results: $("tr-results") };
  const HINTS = {
    teacher: ["(optional: topic or kind of text)", "e.g. A short news story about the weather", "Get a text to translate"],
    own: ["(optional: where the text is from, or what to pay attention to)", "e.g. A page from my textbook; please check the politeness level", "Continue"],
  };

  let sessionId = null;
  let ownText = false;
  let languages = { source: "", target: "" };
  let limits = { recommended: 1500, max: 3000 };
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function applyMode() {
    const mode = $("tr-mode").value;
    const [hint, placeholder, button] = HINTS[mode];
    $("tr-session-hint").textContent = hint;
    $("tr-session-prompt").placeholder = placeholder;
    $("tr-start").textContent = button;
    $("tr-length-label").hidden = mode === "own"; // the learner's own text has its own length
  }

  function fillText(container, text) {
    container.replaceChildren();
    for (const paragraph of text.split(/\n{2,}/)) {
      const p = document.createElement("p");
      p.textContent = paragraph; // textContent: model output is never run as HTML
      container.appendChild(p);
    }
  }

  // Counts the characters of both boxes and warns when a text is long.
  function updateCounts() {
    const number = (n) => n.toLocaleString();
    const source = ownText ? $("tr-source-text").value.trim().length : 0;
    const translation = $("tr-translation").value.trim().length;
    const line = (length) => `${number(length)} characters (recommended: up to ${number(limits.recommended)})`;
    $("tr-source-count").textContent = line(source);
    $("tr-translation-count").textContent = line(translation);
    const longest = Math.max(source, translation);
    const which = source > translation ? "source text" : "translation";
    let warning = "";
    if (longest > limits.max) {
      warning = `Your ${which} is longer than ${number(limits.max)} characters, the most this app can ` +
        "review at once. Please shorten it, or check it in two parts.";
    } else if (longest > limits.recommended) {
      warning = `Your ${which} is longer than the recommended ${number(limits.recommended)} characters. ` +
        "You can still send it, but a small local model will take longer and may review the end less carefully.";
    }
    showNote("tr-long-note", warning);
    $("tr-submit").disabled = longest > limits.max;
  }

  async function startSession() {
    const started = await api("/api/translation/sessions", {
      method: "POST",
      body: JSON.stringify({
        source_language: $("tr-source-language").value.trim(),
        target_language: $("tr-target-language").value.trim(),
        difficulty: $("tr-difficulty").value,
        length: $("tr-length").value,
        system_prompt: $("tr-system-prompt").value,
        session_prompt: $("tr-session-prompt").value,
        with_text: $("tr-mode").value === "teacher",
      }),
    });
    sessionId = started.session_id;
    ownText = !started.source_text;
    languages = { source: $("tr-source-language").value.trim(), target: $("tr-target-language").value.trim() };
    limits = { recommended: started.recommended_chars, max: started.max_chars };
    $("tr-given").hidden = ownText;
    $("tr-own").hidden = !ownText;
    $("tr-given-title").textContent = `Translate this text into ${languages.target}`;
    $("tr-own-label").textContent = `The text in ${languages.source}: type or paste it here`;
    $("tr-translation-title").textContent = `Your translation into ${languages.target}`;
    fillText($("tr-given-text"), started.source_text);
    updateCounts();
  }

  $("tr-mode").addEventListener("change", applyMode);

  $("tr-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("tr-start");
    button.disabled = true;
    if ($("tr-mode").value === "teacher") button.textContent = "Writing the text…";
    try {
      await startSession();
      for (const id of ["tr-source-text", "tr-translation", "tr-source-file", "tr-translation-files"]) $(id).value = "";
      showNote("tr-upload-note", "");
      updateCounts();
      show("write");
      (ownText ? $("tr-source-text") : $("tr-translation")).focus();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      applyMode();
    }
  });

  $("tr-another").addEventListener("click", async () => {
    showError("");
    setBusy(views.write, "Writing another text…");
    try {
      await startSession();
      $("tr-translation").value = ""; // a translation of the old text would not fit the new one
      updateCounts();
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.write, null);
    }
  });

  $("tr-source-text").addEventListener("input", updateCounts);
  $("tr-translation").addEventListener("input", updateCounts);

  // Uploads end up in the text boxes, so the learner always sees and can fix
  // what will be marked.
  $("tr-source-file").addEventListener("change", async () => {
    const file = $("tr-source-file").files[0];
    if (!file) return;
    showError("");
    setBusy(views.write, "Reading your file…");
    try {
      const { text } = await readMaterial(file, { warnWhenLong: false });
      if (!text.trim()) throw new Error("No text was found in that file.");
      $("tr-source-text").value = text.trim();
      updateCounts();
    } catch (error) {
      showError(error.message);
      $("tr-source-file").value = "";
    } finally {
      setBusy(views.write, null);
    }
  });

  $("tr-translation-files").addEventListener("change", async () => {
    const files = [...$("tr-translation-files").files];
    if (!files.length) return;
    showError("");
    showNote("tr-upload-note", "");
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
        const read = await api(`/api/translation/sessions/${sessionId}/handwriting`, {
          method: "POST",
          body: JSON.stringify({ images }),
        });
        $("tr-translation").value = read.text;
        showNote(
          "tr-upload-note",
          "This is how the app read your handwriting. Compare it with your page before you send it: " +
          "where the app misread your writing, change it to what you really wrote, but leave your own " +
          "mistakes as they are. [?] marks a word the app could not read."
        );
      } else {
        setBusy(views.write, "Reading your file…");
        const { text } = await readMaterial(files[0], { warnWhenLong: false });
        if (!text.trim()) throw new Error("No text was found in that file.");
        $("tr-translation").value = text.trim();
        showNote("tr-upload-note", `The text of "${files[0].name}" is now in the box. Check it before you send it.`);
      }
      updateCounts();
    } catch (error) {
      showError(error.message);
      $("tr-translation-files").value = "";
    } finally {
      setBusy(views.write, null);
    }
  });

  $("tr-back").addEventListener("click", () => {
    showError("");
    show("setup");
  });

  // ---------- results ----------

  const rating = (score) => (score === null ? "not rated" : `${score} / 5`);

  function renderResults(result) {
    $("tr-rating").textContent = result.max_total
      ? `Rating: ${result.total} / ${result.max_total}`
      : "Rating: not available";
    const scores = $("tr-scores");
    scores.replaceChildren();
    for (const row of result.scores) {
      const tr = scores.insertRow();
      for (const text of [row.name, rating(row.score), row.comment]) tr.insertCell().textContent = text;
    }
    $("tr-feedback").textContent = result.feedback;

    const list = $("tr-corrections");
    list.replaceChildren();
    $("tr-corrections-title").hidden = result.corrections.length === 0;
    for (const item of result.corrections) {
      const box = document.createElement("div");
      box.className = "correction";
      const parts = [
        ["from", item.source],
        item.yours ? ["was", item.yours] : ["missing", "(left out of your translation)"],
        ["now", item.better],
        ["muted", item.explanation],
      ];
      for (const [className, text] of parts) {
        if (!text) continue;
        const p = document.createElement("p");
        p.className = className;
        p.textContent = text;
        box.appendChild(p);
      }
      list.appendChild(box);
    }
    $("tr-ideal").textContent = result.ideal;
    $("tr-result-source").textContent = result.source_text;
    $("tr-result-translation").textContent = result.translation;
  }

  $("tr-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    if (ownText && $("tr-source-text").value.trim().length < 5) {
      showError("Please enter the source text as well as your translation.");
      return;
    }
    if ($("tr-translation").value.trim().length < 5) {
      showError("Please type or upload your translation first.");
      return;
    }
    setBusy(views.write, "Reading and rating your translation… This can take a minute or two.");
    try {
      const result = await api(`/api/translation/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({
          translation: $("tr-translation").value,
          source_text: ownText ? $("tr-source-text").value : "",
        }),
      });
      finished = { result, date: new Date() };
      saveToHistory({
        feature: "translation",
        language: result.target_language,
        title: `${result.source_language} → ${result.target_language}`,
        score: result.max_total ? result.total : null,
        total: result.max_total || null,
        lines: report(),
        mistakes: result.corrections.map((item) => ({
          prompt: item.source || item.yours || item.better,
          your_answer: item.yours || "",
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

  $("tr-edit").addEventListener("click", () => {
    showError("");
    show("write");
    $("tr-translation").focus();
  });

  $("tr-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // Saves everything as a plain text file.
  // The result as lines of text: for the download and for the history.
  function report() {
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Written translation",
      `Languages: ${result.source_language} -> ${result.target_language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      result.max_total ? `Rating: ${result.total} / ${result.max_total}` : "Rating: not available",
      ...result.scores.map((row) => `  ${row.name}: ${rating(row.score)}${row.comment ? ` - ${row.comment}` : ""}`),
      "",
      "===== SOURCE TEXT =====", "", result.source_text, "",
      "===== YOUR TRANSLATION =====", "", result.translation, "",
      "===== FEEDBACK AND TIPS =====", "", result.feedback, "",
    ];
    if (result.corrections.length) {
      lines.push("===== CORRECTIONS =====");
      result.corrections.forEach((item, i) => {
        lines.push("", `${i + 1}. Source:    ${item.source || "-"}`, `   You wrote: ${item.yours || "(left out)"}`, `   Better:    ${item.better}`);
        if (item.explanation) lines.push(`   Why:       ${item.explanation}`);
      });
      lines.push("");
    }
    lines.push("===== IDEAL VERSION =====", "", result.ideal, "");
    return lines;
  }

  $("tr-download").addEventListener("click", () => {
    if (finished) downloadTextFile("translation", finished.date, report());
  });

  applyMode();
})();
