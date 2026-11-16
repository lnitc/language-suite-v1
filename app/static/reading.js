"use strict";
// Features 8 and 10: reading comprehension and listening comprehension.
// The same exercise twice: in reading the text is shown, in listening it is
// spoken and shown only in the result. `prefix` is the start of the element
// ids ("read" or "listen"). Uses helpers from common.js and voice.js.

function setupComprehension(prefix, kind) {
  const el = (name) => $(`${prefix}-${name}`);
  const listening = kind === "listening";
  const views = { setup: el("setup"), work: el("work"), results: el("results") };
  const LETTERS = ["A", "B", "C", "D"];

  let sessionId = null;
  let questions = [];
  let finished = null; // the last result, for the download

  // ---------- listening: the text is spoken, sentence by sentence ----------
  let spokenText = "";
  let languageCode = "";
  let playRun = 0; // raised to stop a playback that is under way
  let playing = false;
  let plays = 0;

  function sentencesOf(text) {
    return text
      .split(/\n{2,}/)
      .flatMap((paragraph) => paragraph.split(/(?<=[.!?…])\s+|(?<=[。！？])(?![」』）。！？])/))
      .map((sentence) => sentence.trim())
      .filter(Boolean);
  }

  function showPlayer() {
    el("play").textContent = playing ? "■ Stop" : plays ? "▶ Play again" : "▶ Play";
    if (!playing) {
      el("play-status").textContent = plays
        ? `Played ${plays} ${plays === 1 ? "time" : "times"}. You can listen as often as you like.`
        : "Press Play to listen. The text is not shown until you have answered.";
    }
  }

  async function playText() {
    const run = ++playRun;
    const parts = sentencesOf(spokenText);
    showError("");
    playing = true;
    plays += 1;
    showPlayer();
    try {
      for (let i = 0; i < parts.length && run === playRun; i += 1) {
        el("play-status").textContent = `Playing… (sentence ${i + 1} of ${parts.length})`;
        await voice.speak(parts[i], languageCode, Number(el("speed").value));
      }
    } catch (error) {
      showError(error.message);
    }
    if (run === playRun) {
      playing = false;
      showPlayer();
    }
  }

  function stopPlaying() {
    if (!listening) return;
    playRun += 1;
    playing = false;
    voice.stop();
    showPlayer();
  }

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
      const picked = document.querySelector(`input[name="${prefix}-q${i}"]:checked`);
      return picked ? Number(picked.value) : null;
    });
  }

  function updateUnanswered() {
    const open = chosenAnswers().filter((answer) => answer === null).length;
    el("unanswered").textContent = open
      ? `${open} of ${questions.length} questions not answered yet. Unanswered questions count as wrong.`
      : "All questions answered.";
  }

  function drawQuestions() {
    const container = el("questions");
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
        radio.name = `${prefix}-q${i}`;
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
    el("wait").hidden = false;
    el("retry").hidden = true;
    try {
      const made = await api(`/api/reading/sessions/${session}/questions`, { method: "POST" });
      if (session !== sessionId) return; // the learner started something else meanwhile
      questions = made.questions;
      showNote(
        `${prefix}-note`,
        questions.length < made.requested
          ? `The model made ${questions.length} usable ${questions.length === 1 ? "question" : "questions"} instead of ${made.requested}.`
          : ""
      );
      drawQuestions();
      el("form").hidden = false;
    } catch (error) {
      if (session !== sessionId) return;
      showError(error.message);
      el("retry").hidden = false;
    } finally {
      if (session === sessionId) el("wait").hidden = true;
    }
  }

  el("setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = el("start");
    button.disabled = true;
    button.textContent = "Writing the text…";
    try {
      const started = await api("/api/reading/sessions", {
        method: "POST",
        body: JSON.stringify({
          kind,
          language: el("language").value.trim(),
          difficulty: el("difficulty").value,
          length: el("length").value,
          question_count: Number(el("count").value) || 5,
          question_style: el("style").value,
          system_prompt: el("system-prompt").value,
          session_prompt: el("session-prompt").value,
        }),
      });
      sessionId = started.session_id;
      questions = [];
      el("title").textContent = started.title;
      el("title").hidden = !started.title;
      if (listening) {
        spokenText = started.text;
        languageCode = started.language_code;
        plays = 0;
        playing = false;
        voice.fillSelect(el("voice"), el("voice-label"), languageCode);
        showPlayer();
      } else {
        fillText(el("text"), started.text);
      }
      el("form").hidden = true;
      showNote(`${prefix}-note`, "");
      show("work");
      window.scrollTo(0, 0);
      loadQuestions(); // not awaited: the learner can already read or listen
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Create text and questions";
    }
  });

  el("retry").addEventListener("click", () => {
    showError("");
    loadQuestions();
  });

  el("back").addEventListener("click", () => {
    stopPlaying();
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
    el("score").textContent = `Score: ${result.score} / ${result.total}`;
    el("result-title").textContent = result.title;
    fillText(el("result-text"), result.text);
    const container = el("answers");
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

  el("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    stopPlaying();
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

  el("restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  // Saves the text, the questions, both answers and the explanations.
  el("download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const lines = [
      `Language Suite: ${listening ? "Listening" : "Reading"} comprehension`,
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      `Score: ${result.score} / ${result.total}`,
      `Question difficulty: ${result.question_style === "tricky" ? "Tricky" : "Straightforward"}`,
      "",
      listening ? "===== TEXT (what you heard) =====" : "===== TEXT =====",
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
    downloadTextFile(kind, date, lines);
  });

  if (listening) {
    el("play").addEventListener("click", () => (playing ? stopPlaying() : playText()));
    document.addEventListener("feature-change", stopPlaying);
  }
}

setupComprehension("read", "reading");
setupComprehension("listen", "listening");
