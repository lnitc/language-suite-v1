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

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function showWord(progress) {
    $("progress").textContent = `Word ${progress.index + 1} of ${progress.total}`;
    $("direction").textContent = `${languages.source} → ${languages.target}`;
    $("word").textContent = progress.word;
    $("answer").value = "";
    $("answer").focus();
  }

  async function advance(progress) {
    if (!progress.done) {
      showWord(progress);
      return;
    }
    $("progress").textContent = "Checking your answers…";
    const result = await api(`/api/vocabulary/sessions/${sessionId}/result`);
    renderResults(result);
    show("results");
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

  $("setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("start-button");
    button.disabled = true;
    button.textContent = "Preparing words…";
    try {
      const file = $("material").files[0];
      const material = file ? await readFileAsText(file) : "";
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
          material: material.slice(0, 200000),
        }),
      });
      sessionId = progress.session_id;
      show("practice");
      showWord(progress);
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  async function sendAnswer(skip) {
    showError("");
    try {
      const progress = await api(`/api/vocabulary/sessions/${sessionId}/answers`, {
        method: "POST",
        body: JSON.stringify({ answer: skip ? "" : $("answer").value, skip }),
      });
      await advance(progress);
    } catch (error) {
      showError(error.message);
    }
  }

  $("answer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sendAnswer(false);
  });
  $("skip-button").addEventListener("click", () => sendAnswer(true));
  $("restart-button").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });
})();
