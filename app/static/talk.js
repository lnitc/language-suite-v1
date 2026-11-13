"use strict";
// Features 1 and 2: conversation partner and job interview. Uses common.js and voice.js.

(() => {
  const views = { setup: $("talk-setup"), live: $("talk-live"), results: $("talk-results") };
  const KINDS = {
    conversation: {
      title: "Conversation partner",
      partner: "teacher",
      label: "Teacher",
      difficulty: [
        ["beginner", "Beginner (A1)"], ["elementary", "Elementary (A2)"],
        ["intermediate", "Intermediate (B1)"], ["upper_intermediate", "Upper-intermediate (B2)"],
        ["advanced", "Advanced (C1)"],
      ],
      preset: "intermediate",
      systemHint: "You are a friendly, patient language teacher.",
      sessionHint: "e.g. Let's talk about fashion trends",
      materialHint: "(optional: an article or notes to talk about, as text, PDF, Word (.docx) or image)",
    },
    interview: {
      title: "Job interview rehearsal",
      partner: "interviewer",
      label: "Interviewer",
      difficulty: [
        ["kind", "Kind interviewer"], ["medium", "Medium difficulty"],
        ["strict", "Strict interviewer, difficult questions"],
      ],
      preset: "medium",
      systemHint: "You are an experienced job interviewer.",
      sessionHint: "e.g. Ask me questions only about ABC company; the role is marketing manager",
      materialHint: "(optional: your CV or the job description, as PDF, Word (.docx), text or image)",
    },
  };

  let kind = "conversation";
  let sessionId = null;
  let languageCode = "";
  let lastReply = "";
  let done = false;
  let questionCount = null;
  let turn = 0;
  let finished = null; // details of the last finished session, for the download

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function setKind(next) {
    kind = next;
    const config = KINDS[kind];
    $("talk-title").textContent = config.title;
    const select = $("talk-difficulty");
    select.replaceChildren();
    for (const [value, label] of config.difficulty) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    }
    select.value = config.preset;
    $("talk-system-prompt").placeholder = config.systemHint;
    $("talk-session-prompt").placeholder = config.sessionHint;
    $("talk-material-hint").textContent = config.materialHint;
    $("talk-questions-label").hidden = kind !== "interview";
    leaveSession();
  }

  function leaveSession() {
    voice.stop();
    mic.reset();
    sessionId = null;
    show("setup");
  }

  function status(text) { $("talk-status").textContent = text; }

  function addLine(speaker, text) {
    const line = document.createElement("p");
    const who = document.createElement("strong");
    who.textContent = `${speaker}: `;
    line.append(who, text); // text nodes: never run as HTML
    $("talk-transcript").appendChild(line);
  }

  function progress() {
    if (!questionCount || done) return "";
    return `Question ${Math.min(turn + 1, questionCount)} of ${questionCount}. `;
  }

  async function say(text) {
    lastReply = text;
    mic.setEnabled(false);
    status(`${progress()}The ${KINDS[kind].partner} is speaking…`);
    try {
      await voice.speak(text, languageCode, Number($("talk-speed").value));
    } catch (error) {
      showError(error.message);
    }
    if (!sessionId) return;
    if (done) {
      status("The session is over. Press the button below for your feedback.");
      $("talk-end").textContent = "Show feedback";
      $("talk-end").classList.add("primary");
    } else {
      mic.setEnabled(true);
      status(`${progress()}Your turn: press the microphone, speak, then press it again.`);
    }
  }

  const mic = voice.attachMic($("talk-mic"), {
    language: () => languageCode,
    onText: async (text) => {
      addLine("You", text);
      mic.setEnabled(false);
      status(`The ${KINDS[kind].partner} is thinking…`);
      try {
        const result = await api(`/api/talk/sessions/${sessionId}/turns`, {
          method: "POST",
          body: JSON.stringify({ text }),
        });
        done = result.done;
        turn = result.turn;
        addLine(KINDS[kind].label, result.reply);
        say(result.reply); // not awaited: the microphone button returns to normal meanwhile
      } catch (error) {
        $("talk-transcript").lastChild.remove(); // that turn did not count
        mic.setEnabled(true);
        status("Something went wrong. Please say that again.");
        throw error;
      }
    },
  });

  $("talk-setup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("talk-start");
    button.disabled = true;
    button.textContent = "Getting ready…";
    try {
      const { text: material, image, note } = await readMaterial(
        $("talk-material").files[0], { allowImages: true }
      );
      showNote("talk-note", note);
      const started = await api("/api/talk/sessions", {
        method: "POST",
        body: JSON.stringify({
          kind,
          language: $("talk-language").value.trim(),
          difficulty: $("talk-difficulty").value,
          system_prompt: $("talk-system-prompt").value,
          session_prompt: $("talk-session-prompt").value,
          question_count: Number($("talk-questions").value) || 5,
          material,
          image,
        }),
      });
      sessionId = started.session_id;
      languageCode = started.language_code;
      questionCount = started.question_count;
      done = false;
      turn = 0;
      $("talk-transcript").replaceChildren();
      $("talk-end").textContent = "End session and get feedback";
      $("talk-end").classList.remove("primary");
      $("talk-end").disabled = false;
      voice.fillSelect($("talk-voice"), $("talk-voice-label"), languageCode);
      show("live");
      addLine(KINDS[kind].label, started.reply);
      say(started.reply);
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Start session";
    }
  });

  $("talk-repeat").addEventListener("click", () => {
    if (lastReply) say(lastReply);
  });

  $("talk-show-text").addEventListener("change", (event) => {
    $("talk-transcript").hidden = !event.target.checked;
  });

  $("talk-end").addEventListener("click", async () => {
    showError("");
    voice.stop();
    await mic.reset();
    mic.setEnabled(false);
    const button = $("talk-end");
    button.disabled = true;
    status("Writing your feedback…");
    try {
      const result = await api(`/api/talk/sessions/${sessionId}/finish`, { method: "POST" });
      finished = {
        title: KINDS[kind].title,
        kind,
        language: $("talk-language").value.trim(),
        date: new Date(),
        feedback: result.feedback,
        transcript: result.transcript,
      };
      $("talk-feedback").textContent = result.feedback;
      const log = $("talk-final-transcript");
      log.replaceChildren();
      for (const row of result.transcript) {
        const line = document.createElement("p");
        const who = document.createElement("strong");
        who.textContent = `${row.speaker}: `;
        line.append(who, row.text);
        log.appendChild(line);
      }
      show("results");
    } catch (error) {
      showError(error.message);
      status("The feedback could not be written. Press the button to try again.");
    } finally {
      button.disabled = false;
    }
  });

  $("talk-restart").addEventListener("click", leaveSession);

  // Saves the script and the feedback as a plain text file.
  $("talk-download").addEventListener("click", () => {
    if (!finished) return;
    const stamp = dateStamp(finished.date);
    downloadTextFile(finished.kind, finished.date, [
      `Language Suite: ${finished.title}`,
      `Language: ${finished.language}`,
      `Date: ${stamp.day} ${stamp.time}`,
      "",
      "===== FEEDBACK =====",
      "",
      finished.feedback,
      "",
      "===== SCRIPT =====",
      "",
      ...finished.transcript.map((row) => `${row.speaker}: ${row.text}`),
      "",
    ]);
  });

  document.addEventListener("feature-change", (event) => {
    if (event.detail.feature === "talk") {
      // Returning to the same tab keeps a running session.
      if (event.detail.kind !== kind || !sessionId) setKind(event.detail.kind);
    } else if (sessionId && views.live.hidden === false) { voice.stop(); mic.reset(); }
  });

  setKind("conversation");
})();
