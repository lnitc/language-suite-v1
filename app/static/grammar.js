"use strict";
// Feature 13: grammar drills. Uses helpers from common.js.

(() => {
  const views = { setup: $("gr-setup"), work: $("gr-work"), results: $("gr-results") };
  const VERDICTS = {
    correct: ["Correct", "right"],
    accepted: ["Correct (accepted by the teacher)", "right"],
    wrong: ["Wrong", "wrong"],
    skipped: ["Not answered", "none"],
  };

  let sessionId = null;
  let items = [];
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  const fields = () => [...document.querySelectorAll("#gr-items [data-answer]")];

  // An answer counts as given if something was typed, and for a correction
  // only if the sentence was actually changed.
  function answers() {
    return fields().map((field, i) =>
      items[i].kind === "fix" && field.value.trim() === items[i].sentence ? "" : field.value.trim());
  }

  function updateUnanswered() {
    const open = answers().filter((answer) => !answer).length;
    $("gr-unanswered").textContent = open
      ? `${open} of ${items.length} not answered yet. Unanswered items count as wrong.`
      : "All items answered.";
  }

  function drawItems() {
    const container = $("gr-items");
    container.replaceChildren();
    for (const item of items) {
      const box = document.createElement("div");
      box.className = "drill";
      const task = document.createElement("p");
      task.className = "task";
      task.textContent = `${item.number}. ${item.task}`;
      const sentence = document.createElement("p");
      sentence.className = "drill-sentence";
      sentence.textContent = item.sentence; // textContent: model output is never run as HTML
      if (item.hint) {
        const hint = document.createElement("span");
        hint.className = "hint";
        hint.textContent = `  ${item.hint.startsWith("(") ? item.hint : `(${item.hint})`}`;
        sentence.appendChild(hint);
      }
      const field = document.createElement("input");
      field.dataset.answer = "1";
      field.autocomplete = "off";
      field.spellcheck = false;
      field.maxLength = 600;
      if (item.kind === "gap") {
        field.placeholder = "What goes in the blank?";
        field.setAttribute("aria-label", `Item ${item.number}: what goes in the blank`);
      } else {
        field.value = item.sentence; // the learner edits the sentence itself
        field.setAttribute("aria-label", `Item ${item.number}: the corrected sentence`);
      }
      field.addEventListener("input", updateUnanswered);
      box.append(task, sentence, field);
      container.appendChild(box);
    }
    updateUnanswered();
  }

  $("gr-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("gr-start");
    button.disabled = true;
    button.textContent = "Writing the exercises…";
    try {
      const started = await api("/api/grammar/sessions", {
        method: "POST",
        body: JSON.stringify({
          language: $("gr-language").value.trim(),
          difficulty: $("gr-difficulty").value,
          topic: $("gr-topic").value.trim(),
          exercise: $("gr-exercise").value,
          count: Number($("gr-count").value) || 5,
          system_prompt: $("gr-system-prompt").value,
          session_prompt: $("gr-session-prompt").value,
        }),
      });
      sessionId = started.session_id;
      items = started.items;
      showNote(
        "gr-note",
        items.length < started.requested
          ? `The model made ${items.length} usable ${items.length === 1 ? "item" : "items"} instead of ${started.requested}.`
          : ""
      );
      drawItems();
      show("work");
      window.scrollTo(0, 0);
      const first = fields()[0];
      if (first) first.focus();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Create exercises";
    }
  });

  $("gr-back").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  function line(label, text, className) {
    const p = document.createElement("p");
    if (className) p.className = className;
    const strong = document.createElement("strong");
    strong.textContent = `${label} `;
    p.append(strong, text);
    return p;
  }

  function renderResults(result) {
    $("gr-score").textContent = `Score: ${result.score} / ${result.total}`;
    const container = $("gr-answers");
    container.replaceChildren();
    for (const row of result.items) {
      const [word, kind] = VERDICTS[row.status];
      const box = document.createElement("div");
      box.className = "answer";
      const heading = document.createElement("h3");
      heading.textContent = `${row.number}. ${row.sentence}${row.hint ? `  ${row.hint}` : ""}`;
      const badge = document.createElement("span");
      badge.className = `badge ${kind}`;
      badge.textContent = word;
      heading.appendChild(badge);
      box.appendChild(heading);
      const right = row.status === "correct" || row.status === "accepted";
      box.appendChild(line("Your answer:", row.your_answer || "(not answered)", `given ${right ? "right" : "wrong"}`));
      if (row.status !== "correct") box.appendChild(line("Correct:", row.correct_answers.join("  /  ")));
      if (row.comment) box.appendChild(line("About your answer:", row.comment));
      if (row.explanation) box.appendChild(line("The rule:", row.explanation));
      container.appendChild(box);
    }
  }

  $("gr-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    setBusy(views.work, "Checking your answers…");
    try {
      const result = await api(`/api/grammar/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ answers: answers() }),
      });
      finished = { result, date: new Date() };
      saveToHistory({
        feature: "grammar",
        language: result.language,
        title: result.topic || "",
        score: result.score,
        total: result.total,
        lines: report(),
        mistakes: result.items
          .filter((row) => row.status === "wrong" || row.status === "skipped")
          .map((row) => ({
            prompt: `${row.sentence}${row.hint ? `  ${row.hint}` : ""}`,
            your_answer: row.your_answer,
            correct: row.correct_answers.join("  /  "),
            note: row.explanation,
          })),
      });
      renderResults(result);
      show("results");
      window.scrollTo(0, 0);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.work, null);
    }
  });

  $("gr-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // The result as lines of text: for the download and for the history.
  function report() {
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Grammar drills",
      `Language: ${result.language}`,
      ...(result.topic ? [`Grammar point: ${result.topic}`] : []),
      `Date: ${stamp.day} ${stamp.time}`,
      `Score: ${result.score} / ${result.total}`,
      "",
      "===== EXERCISES =====",
    ];
    for (const row of result.items) {
      lines.push(
        "",
        `${row.number}. ${row.task}: ${row.sentence}${row.hint ? `  ${row.hint}` : ""}  [${VERDICTS[row.status][0]}]`,
        `   Your answer: ${row.your_answer || "(not answered)"}`,
        `   Correct: ${row.correct_answers.join("  /  ")}`
      );
      if (row.comment) lines.push(`   About your answer: ${row.comment}`);
      if (row.explanation) lines.push(`   The rule: ${row.explanation}`);
    }
    lines.push("");
    return lines;
  }

  $("gr-download").addEventListener("click", () => {
    if (finished) downloadTextFile("grammar", finished.date, report());
  });
})();
