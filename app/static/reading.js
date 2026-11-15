"use strict";
// Feature 8: reading comprehension. Uses helpers from common.js.

(() => {
  const views = { setup: $("read-setup"), work: $("read-work"), results: $("read-results") };
  const LETTERS = ["A", "B", "C", "D"];

  let sessionId = null;
  let questions = [];
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  // Paragraphs are separated by empty lines.
  function fillText(container, text) {
    container.replaceChildren();
    for (const paragraph of text.split(/\n{2,}/)) {
      const p = document.createElement("p");
      p.textContent = paragraph; // textContent: model output is never run as HTML
      container.appendChild(p);
    }
  }

  function chosenAnswers() {
    return questions.map((_, i) => {
      const picked = document.querySelector(`input[name="read-q${i}"]:checked`);
      return picked ? Number(picked.value) : null;
    });
  }

  function updateUnanswered() {
    const open = chosenAnswers().filter((answer) => answer === null).length;
    $("read-unanswered").textContent = open
      ? `${open} of ${questions.length} questions not answered yet. Unanswered questions count as wrong.`
      : "All questions answered.";
  }

  function drawQuestions() {
    const container = $("read-questions");
    container.replaceChildren();
    questions.forEach((item, i) => {
      const fieldset = document.createElement("fieldset");
      fieldset.className = "question";
      const legend = document.createElement("legend");
      legend.textContent = `${item.number}. ${item.question}`;
      fieldset.appendChild(legend);
      item.options.forEach((option, k) => {
        const label = document.createElement("label");
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = `read-q${i}`;
        radio.value = String(k);
        radio.addEventListener("change", updateUnanswered);
        const text = document.createElement("span");
        text.textContent = `${LETTERS[k]}. ${option}`;
        label.append(radio, text);
        fieldset.appendChild(label);
      });
      container.appendChild(fieldset);
    });
    updateUnanswered();
  }

  // Step 2: the questions arrive while the learner is already reading.
  async function loadQuestions() {
    const session = sessionId;
    $("read-wait").hidden = false;
    $("read-retry").hidden = true;
    try {
      const made = await api(`/api/reading/sessions/${session}/questions`, { method: "POST" });
      if (session !== sessionId) return; // the learner started something else meanwhile
      questions = made.questions;
      showNote(
        "read-note",
        questions.length < made.requested
          ? `The model made ${questions.length} usable questions instead of ${made.requested}.`
          : ""
      );
      drawQuestions();
      $("read-form").hidden = false;
    } catch (error) {
      if (session !== sessionId) return;
      showError(error.message);
      $("read-retry").hidden = false;
    } finally {
      if (session === sessionId) $("read-wait").hidden = true;
    }
  }

  $("read-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("read-start");
    button.disabled = true;
    button.textContent = "Writing the text…";
    try {
      const started = await api("/api/reading/sessions", {
        method: "POST",
        body: JSON.stringify({
          language: $("read-language").value.trim(),
          difficulty: $("read-difficulty").value,
          length: $("read-length").value,
          question_count: Number($("read-count").value) || 5,
          question_style: $("read-style").value,
          system_prompt: $("read-system-prompt").value,
          session_prompt: $("read-session-prompt").value,
        }),
      });
      sessionId = started.session_id;
      questions = [];
      $("read-title").textContent = started.title;
      $("read-title").hidden = !started.title;
      fillText($("read-text"), started.text);
      $("read-form").hidden = true;
      showNote("read-note", "");
      show("work");
      window.scrollTo(0, 0);
      loadQuestions(); // not awaited: the text is on screen meanwhile
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Create text and questions";
    }
  });

  $("read-retry").addEventListener("click", () => {
    showError("");
    loadQuestions();
  });

  $("read-back").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // ---------- results ----------

  function verdict(row) {
    if (row.is_correct) return ["Correct", "right"];
    return row.chosen === null ? ["Not answered", "none"] : ["Wrong", "wrong"];
  }

  function line(label, text) {
    const p = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = `${label} `;
    p.append(strong, text);
    return p;
  }

  function renderResults(result) {
    $("read-score").textContent = `Score: ${result.score} / ${result.total}`;
    $("read-result-title").textContent = result.title;
    fillText($("read-result-text"), result.text);
    const container = $("read-answers");
    container.replaceChildren();
    for (const row of result.questions) {
      const box = document.createElement("div");
      box.className = "answer";
      const heading = document.createElement("h3");
      heading.textContent = `${row.number}. ${row.question}`;
      const [word, kind] = verdict(row);
      const badge = document.createElement("span");
      badge.className = `badge ${kind}`;
      badge.textContent = word;
      heading.appendChild(badge);
      const list = document.createElement("ul");
      row.options.forEach((option, k) => {
        const li = document.createElement("li");
        let mark = "";
        if (k === row.correct) {
          li.className = "right";
          mark = row.chosen === k ? "  ✓ correct, your answer" : "  ✓ correct answer";
        } else if (k === row.chosen) {
          li.className = "chosen-wrong";
          mark = "  ✗ your answer";
        }
        li.textContent = `${LETTERS[k]}. ${option}${mark}`;
        list.appendChild(li);
      });
      box.append(heading, list);
      if (row.explanation) box.appendChild(line("Why this is correct:", row.explanation));
      if (row.why_wrong) box.appendChild(line("Why your answer is wrong:", row.why_wrong));
      container.appendChild(box);
    }
  }

  $("read-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    setBusy(views.work, "Checking your answers…");
    try {
      const result = await api(`/api/reading/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ answers: chosenAnswers() }),
      });
      finished = { result, date: new Date() };
      renderResults(result);
      show("results");
      window.scrollTo(0, 0);
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.work, null);
    }
  });

  $("read-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // Saves the text, the questions, both answers and the explanations.
  $("read-download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      "Language Suite: Reading comprehension",
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      `Score: ${result.score} / ${result.total}`,
      `Question difficulty: ${result.question_style === "tricky" ? "Tricky" : "Straightforward"}`,
      "",
      "===== TEXT =====",
      "",
    ];
    if (result.title) lines.push(result.title, "");
    lines.push(result.text, "", "===== QUESTIONS AND ANSWERS =====");
    for (const row of result.questions) {
      lines.push("", `${row.number}. ${row.question}  [${verdict(row)[0]}]`);
      row.options.forEach((option, k) => lines.push(`   ${LETTERS[k]}. ${option}`));
      lines.push(
        `   Your answer: ${row.chosen === null ? "(not answered)" : LETTERS[row.chosen]}`,
        `   Correct answer: ${LETTERS[row.correct]}`
      );
      if (row.explanation) lines.push(`   Why this is correct: ${row.explanation}`);
      if (row.why_wrong) lines.push(`   Why your answer is wrong: ${row.why_wrong}`);
    }
    lines.push("");
    downloadTextFile("reading", date, lines);
  });
})();
