"use strict";
// Feature 5: dictation. Uses helpers from common.js.

(() => {
  const views = {
    setup: $("dict-setup"),
    practice: $("dict-practice"),
    results: $("dict-results"),
  };
  const player = new Audio(); // used when a speech server makes the audio

  let sessionId = null;
  let speech = { mode: "browser", language_code: "", texts: [] };
  let total = 0;
  let index = 0;
  let answers = [];
  let played = [];
  let audioUrls = {};
  let finished = null; // the last result, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function stopAudio() {
    player.pause();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  // ---------- browser voices ----------

  function matchingVoices() {
    const voices = window.speechSynthesis.getVoices();
    const primary = speech.language_code.split("-")[0].toLowerCase();
    if (!primary) return voices;
    return voices.filter((voice) => voice.lang.toLowerCase().split(/[-_]/)[0] === primary);
  }

  function fillVoices() {
    if (speech.mode !== "browser" || !sessionId) return;
    const select = $("dict-voice");
    const previous = select.value;
    const voices = matchingVoices();
    select.replaceChildren();
    for (const voice of voices) {
      const option = document.createElement("option");
      option.value = voice.name;
      option.textContent = `${voice.name} (${voice.lang})`;
      select.appendChild(option);
    }
    if (voices.some((voice) => voice.name === previous)) select.value = previous;
    $("dict-voice-label").hidden = voices.length === 0;
    if (voices.length === 0 && window.speechSynthesis.getVoices().length > 0) {
      showError(
        `This browser has no voice for ${$("dict-language").value.trim()}. ` +
        'Add one in Windows (see "Voices" in the README), or use a speech server.'
      );
    }
  }

  function speakInBrowser(text) {
    if (!("speechSynthesis" in window)) {
      throw new Error("This browser cannot speak text. Try Chrome or Edge, or use a speech server.");
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = window.speechSynthesis
      .getVoices()
      .find((candidate) => candidate.name === $("dict-voice").value);
    if (voice) utterance.voice = voice;
    utterance.lang = voice ? voice.lang : speech.language_code;
    utterance.rate = Number($("dict-speed").value);
    window.speechSynthesis.speak(utterance);
  }

  async function playFromServer(sentence) {
    if (!audioUrls[sentence]) {
      const response = await request(`/api/dictation/sessions/${sessionId}/audio/${sentence}`);
      audioUrls[sentence] = URL.createObjectURL(await response.blob());
    }
    if (sentence !== index) return; // the learner moved on while it loaded
    player.src = audioUrls[sentence];
    player.playbackRate = Number($("dict-speed").value);
    await player.play();
  }

  async function play() {
    showError("");
    const button = $("dict-play");
    try {
      if (speech.mode === "browser") {
        speakInBrowser(speech.texts[index]);
      } else {
        button.disabled = true;
        await playFromServer(index);
      }
      played[index] = true;
      button.textContent = "↻ Repeat";
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
    }
  }

  // ---------- practice ----------

  function showSentence(autoplay) {
    stopAudio();
    $("dict-progress").textContent = `Sentence ${index + 1} of ${total}`;
    $("dict-play").textContent = played[index] ? "↻ Repeat" : "▶ Play";
    $("dict-answer").value = answers[index] || "";
    $("dict-back").disabled = index === 0;
    $("dict-next").textContent = index === total - 1 ? "Finish and check" : "Next sentence →";
    $("dict-answer").focus();
    if (autoplay && !played[index]) play();
  }

  async function finish() {
    setBusy(views.practice, "Checking your dictation…");
    try {
      const result = await api(`/api/dictation/sessions/${sessionId}/submit`, {
        method: "POST",
        body: JSON.stringify({ answers }),
      });
      finished = { result, date: new Date() };
      renderResults(result);
      show("results");
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(views.practice, null);
    }
  }

  function tokenLine(label, tokens, joiner, badClass) {
    const line = document.createElement("p");
    const title = document.createElement("span");
    title.className = "muted";
    title.textContent = `${label} `;
    line.appendChild(title);
    if (tokens.length === 0) line.append("(nothing typed)");
    tokens.forEach((token, i) => {
      const span = document.createElement("span");
      span.textContent = token.text; // textContent: never run as HTML
      if (!token.ok) span.className = badClass;
      line.appendChild(span);
      if (joiner && i < tokens.length - 1) line.append(joiner);
    });
    return line;
  }

  function renderResults(result) {
    $("dict-score").textContent =
      `Accuracy: ${result.accuracy}% (${result.correct} of ${result.total} correct)`;
    $("dict-feedback").textContent =
      result.feedback || "The teacher's comment could not be generated, but the marking below is complete.";
    const container = $("dict-sentences");
    container.replaceChildren();
    for (const row of result.sentences) {
      const block = document.createElement("div");
      block.className = "sentence";
      const heading = document.createElement("p");
      heading.className = "muted";
      heading.textContent = `Sentence ${row.number}: ${row.correct} of ${row.total}`;
      block.append(
        heading,
        tokenLine("Original:", row.expected, row.joiner, "miss"),
        tokenLine("You typed:", row.typed, row.joiner, "extra")
      );
      container.appendChild(block);
    }
  }

  // ---------- events ----------

  $("dict-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("dict-start-button");
    button.disabled = true;
    button.textContent = "Writing the text…";
    try {
      const { text: material, note } = await readMaterial($("dict-material").files[0]);
      showNote("dict-note", note);
      const started = await api("/api/dictation/sessions", {
        method: "POST",
        body: JSON.stringify({
          language: $("dict-language").value.trim(),
          difficulty: $("dict-difficulty").value,
          length: $("dict-length").value,
          system_prompt: $("dict-system-prompt").value,
          session_prompt: $("dict-session-prompt").value,
          material,
        }),
      });
      Object.values(audioUrls).forEach((url) => URL.revokeObjectURL(url));
      sessionId = started.session_id;
      speech = started.speech;
      total = started.total;
      index = 0;
      answers = new Array(total).fill("");
      played = new Array(total).fill(false);
      audioUrls = {};
      $("dict-voice-label").hidden = true;
      show("practice");
      fillVoices();
      showSentence(false); // the first sentence waits for the Play button
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  $("dict-play").addEventListener("click", play);

  $("dict-answer-form").addEventListener("submit", (event) => {
    event.preventDefault();
    answers[index] = $("dict-answer").value;
    if (index === total - 1) {
      stopAudio();
      finish();
    } else {
      index += 1;
      showSentence(true);
    }
  });

  // Enter moves on; Shift+Enter makes a new line.
  $("dict-answer").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("dict-answer-form").requestSubmit();
    }
  });

  $("dict-back").addEventListener("click", () => {
    answers[index] = $("dict-answer").value;
    if (index > 0) index -= 1;
    showSentence(false);
  });

  // Saves the result as a plain text file: both versions of every sentence,
  // the words that differ, and the teacher's feedback.
  $("dict-download").addEventListener("click", () => {
    if (!finished) return;
    const { result, date } = finished;
    const stamp = dateStamp(date);
    const differing = (tokens) => tokens.filter((token) => !token.ok).map((token) => token.text);
    const lines = [
      "Language Suite: Dictation",
      `Language: ${result.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      `Accuracy: ${result.accuracy}% (${result.correct} of ${result.total} correct)`,
      "Punctuation and capital letters were not marked.",
      "",
      "===== FEEDBACK =====",
      "",
      result.feedback || "(No teacher's comment was generated.)",
      "",
      "===== SENTENCE BY SENTENCE =====",
    ];
    for (const row of result.sentences) {
      const missed = differing(row.expected);
      const extra = differing(row.typed);
      lines.push(
        "",
        `Sentence ${row.number} (${row.correct} of ${row.total} correct)`,
        `Correct:   ${row.original}`,
        `You typed: ${row.typed.length ? row.typed.map((token) => token.text).join(row.joiner) : "(nothing typed)"}`
      );
      if (missed.length) lines.push(`Missed or wrong: ${missed.join(row.joiner ? ", " : " ")}`);
      if (extra.length) lines.push(`Not matching in your text: ${extra.join(row.joiner ? ", " : " ")}`);
    }
    lines.push("");
    downloadTextFile("dictation", date, lines);
  });

  $("dict-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  document.addEventListener("feature-change", stopAudio);
  if ("speechSynthesis" in window) {
    window.speechSynthesis.addEventListener("voiceschanged", fillVoices);
  }
})();
