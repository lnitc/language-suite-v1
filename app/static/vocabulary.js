"use strict";
// Feature 4: vocabulary practice. Uses helpers from common.js.

(() => {
  const views = {
    setup: $("vocab-setup"),
    practice: $("vocab-practice"),
    results: $("vocab-results"),
  };
  const STATUS_LABELS = {
    correct: "Correct",
    accepted: "Correct (accepted by teacher)",
    wrong: "Wrong",
    skipped: "Skipped",
  };

  let sessionId = null;
  let languages = { source: "", target: "" };
  let codes = { source: "", target: "" };
  let voiceMode = false;
  let sending = false;
  let awaitingResult = false;
  let finished = null; // the last result, for the download
  const answerButtons = [$("answer-form").querySelector("button[type=submit]"), $("skip-button")];

  // Voice mode: the word is also spoken, and the answer can be said aloud.
  const mic = voice.attachMic($("vocab-mic"), {
    language: () => codes.target,
    onText: async (text) => {
      $("answer").value = text.replace(/[.。!?！？]+$/u, "");
      $("answer").focus();
    },
  });

  function speakWord() {
    voice.speak($("word").textContent, codes.source).catch((error) => showError(error.message));
  }

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function showWord(progress) {
    $("progress").textContent = `Word ${progress.index + 1} of ${progress.total}`;
    $("direction").textContent = `${languages.source} → ${languages.target}`;
    $("word").textContent = progress.word;
    $("answer").value = "";
    $("answer").focus();
    if (voiceMode) speakWord();
  }

  async function advance(progress) {
    if (!progress.done) {
      showWord(progress);
      return;
    }
    awaitingResult = true; // all words are answered; only the result is missing
    setBusy(views.practice, "Checking your answers…");
    try {
      const result = await api(`/api/vocabulary/sessions/${sessionId}/result`);
      awaitingResult = false;
      finished = { result, date: new Date(), voiceMode };
      saveToHistory({
        feature: "vocabulary",
        language: languages.target,
        title: `${languages.source} → ${languages.target}`,
        score: result.score,
        total: result.total,
        lines: report(),
        mistakes: result.items
          .filter((item) => item.status === "wrong" || item.status === "skipped")
          .map((item) => ({
            prompt: item.word,
            your_answer: item.your_answer || "",
            correct: item.correct_translations.join(", "),
            // enough to practise the word again from "My mistakes"
            extra: { source_language: languages.source, translations: item.correct_translations, codes },
          })),
        mastered: result.items
          .filter((item) => item.status === "correct" || item.status === "accepted")
          .map((item) => item.word),
      });
      renderResults(result);
      show("results");
    } finally {
      setBusy(views.practice, null);
    }
  }

  function renderResults(result) {
    const percent = Math.round((result.score / result.total) * 100);
    $("score").textContent = `Score: ${result.score} / ${result.total} (${percent}%)`;
    const rows = $("result-rows");
    rows.replaceChildren();
    for (const item of result.items) {
      const tr = document.createElement("tr");
      const cells = [
        item.word,
        item.your_answer || "-",
        item.correct_translations.join(", "),
        STATUS_LABELS[item.status] || item.status,
      ];
      cells.forEach((text, i) => {
        const td = document.createElement("td");
        td.textContent = text; // textContent: model output is never run as HTML
        if (i === 3) td.className = `status-${item.status}`;
        tr.appendChild(td);
      });
      rows.appendChild(tr);
    }
  }

  function beginPractice(progress) {
    sessionId = progress.session_id;
    awaitingResult = false;
    voiceMode = $("mode").value === "voice";
    $("vocab-voice-tools").hidden = !voiceMode;
    $("answer").placeholder = voiceMode
      ? "Say the translation with the microphone, or type it"
      : "Type the translation";
    show("practice");
    showWord(progress);
  }

  // "My mistakes" sends words here to be practised again: no model is
  // needed, because the accepted translations are already known.
  document.addEventListener("practise-words", async (event) => {
    const { source, target, words } = event.detail;
    showError("");
    show("setup");
    showNote("vocab-note", `Practising ${words.length} ${words.length === 1 ? "word" : "words"} from your mistakes.`);
    setBusy(views.setup, "Preparing your words…");
    try {
      languages = { source, target };
      const progress = await api("/api/vocabulary/sessions", {
        method: "POST",
        body: JSON.stringify({ source_language: source, target_language: target, words }),
      });
      codes = event.detail.codes || { source: "", target: "" };
      beginPractice(progress);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.setup, null);
    }
  });

  $("setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("start-button");
    button.disabled = true;
    button.textContent = "Preparing words…";
    try {
      const { text: material, note } = await readMaterial($("material").files[0]);
      showNote("vocab-note", note);
      languages = {
        source: $("source-language").value.trim(),
        target: $("target-language").value.trim(),
      };
      const progress = await api("/api/vocabulary/sessions", {
        method: "POST",
        body: JSON.stringify({
          source_language: languages.source,
          target_language: languages.target,
          count: Number($("count").value),
          system_prompt: $("system-prompt").value,
          session_prompt: $("session-prompt").value,
          material,
        }),
      });
      codes = { source: progress.source_language_code, target: progress.target_language_code };
      beginPractice(progress);
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  async function sendAnswer(skip) {
    if (sending) return; // a second click must not answer the next word too
    sending = true;
    answerButtons.forEach((button) => { button.disabled = true; });
    showError("");
    voice.stop();
    await mic.reset();
    try {
      if (awaitingResult) {
        await advance({ done: true }); // the result failed before: just ask again
      } else {
        const progress = await api(`/api/vocabulary/sessions/${sessionId}/answers`, {
          method: "POST",
          body: JSON.stringify({ answer: skip ? "" : $("answer").value, skip }),
        });
        await advance(progress);
      }
    } catch (error) {
      showError(error.message);
    } finally {
      sending = false;
      answerButtons.forEach((button) => { button.disabled = false; });
    }
  }

  $("answer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sendAnswer(false);
  });
  $("skip-button").addEventListener("click", () => sendAnswer(true));
  $("vocab-hear").addEventListener("click", speakWord);
  document.addEventListener("feature-change", () => { mic.reset(); });
  // Saves the result as a plain text file: every word with the learner's
  // translation, the correct translations and the outcome.
  // The result as lines of text: for the download and for the history.
  function report() {
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const percent = Math.round((result.score / result.total) * 100);
    const lines = [
      "Language Suite: Vocabulary practice",
      `Languages: ${languages.source} -> ${languages.target}`,
      `Type of training: ${finished.voiceMode ? "Voice" : "Text"}`,
      `Date: ${stamp.day} ${stamp.time}`,
      `Score: ${result.score} / ${result.total} (${percent}%)`,
      "",
      "===== WORDS =====",
    ];
    result.items.forEach((item, i) => {
      lines.push(
        "",
        `${i + 1}. ${item.word}`,
        `   Your translation: ${item.your_answer || "-"}`,
        `   Correct translations: ${item.correct_translations.join(", ")}`,
        `   Result: ${STATUS_LABELS[item.status] || item.status}`
      );
    });
    const toReview = result.items.filter((item) => item.status === "wrong" || item.status === "skipped");
    if (toReview.length) {
      lines.push("", "===== WORDS TO REVIEW =====", "");
      toReview.forEach((item) => lines.push(`${item.word} = ${item.correct_translations.join(", ")}`));
    }
    lines.push("");
    return lines;
  }

  $("vocab-download").addEventListener("click", () => {
    if (finished) downloadTextFile("vocabulary", finished.date, report());
  });

  $("restart-button").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });
})();
