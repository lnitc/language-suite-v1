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
    delete select.dataset.auto; // rebuilt: the saved level may be applied again (conversation only)
    $("talk-system-prompt").placeholder = config.systemHint;
    $("talk-session-prompt").placeholder = config.sessionHint;
    $("talk-material-hint").textContent = config.materialHint;
    $("talk-questions-label").hidden = kind !== "interview";
    leaveSession();
  }

  function leaveSession() {
    speechRun += 1;
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

  // Hands-free is a choice (off unless ticked), remembered in this browser.
  const handsFree = () => $("talk-handsfree").checked;
  try { $("talk-handsfree").checked = localStorage.getItem("talk-handsfree") === "1"; } catch { /* optional */ }
  $("talk-handsfree").addEventListener("change", () => {
    try { localStorage.setItem("talk-handsfree", handsFree() ? "1" : "0"); } catch { /* optional */ }
    if (handsFree() && sessionId && !done && !$("talk-mic").disabled) mic.start();
  });

  let speechRun = 0; // raised to cancel sentences that are still waiting to be spoken

  // What happens when the partner has finished speaking.
  function afterSpeaking() {
    if (!sessionId) return;
    if (done) {
      status("The session is over. Press the button below for your feedback.");
      $("talk-end").textContent = "Show feedback";
      $("talk-end").classList.add("primary");
      return;
    }
    mic.setEnabled(true);
    if (handsFree() && !$("feature-talk").hidden) { // not while another feature is open
      status(`${progress()}Listening: speak when you are ready. I stop when you pause for two seconds.`);
      mic.start();
    } else {
      status(`${progress()}Your turn: press the microphone, speak, then press it again.`);
    }
  }

  async function say(text) {
    const run = ++speechRun;
    lastReply = text;
    mic.setEnabled(false);
    status(`${progress()}The ${KINDS[kind].partner} is speaking…`);
    try {
      await voice.speak(text, languageCode, Number($("talk-speed").value));
    } catch (error) {
      showError(error.message);
    }
    if (run === speechRun) afterSpeaking();
  }

  // Sends the learner's words and speaks the reply sentence by sentence as
  // the model writes it, instead of waiting for the whole reply.
  async function streamTurn(text) {
    const run = ++speechRun;
    const response = await request(`/api/talk/sessions/${sessionId}/turns/stream`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    let speaking = Promise.resolve();
    let final = null;

    const handle = (data) => {
      if (data.error) throw new Error(data.error);
      if (data.sentence) {
        speaking = speaking.then(() => {
          if (run !== speechRun) return null; // cancelled meanwhile
          status(`${progress()}The ${KINDS[kind].partner} is speaking…`);
          return voice
            .speak(data.sentence, languageCode, Number($("talk-speed").value))
            .catch((error) => showError(error.message));
        });
      } else if ("done" in data) {
        final = data;
      }
    };

    try {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done: finished } = await reader.read();
        if (finished) break;
        buffer += decoder.decode(value, { stream: true });
        let end;
        while ((end = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, end).trim();
          buffer = buffer.slice(end + 1);
          if (line) handle(JSON.parse(line));
        }
      }
      if (buffer.trim()) handle(JSON.parse(buffer));
      if (!final) throw new Error("The reply was cut off. Please say that again.");
    } catch (error) {
      speechRun += 1; // drop what was still waiting to be spoken
      voice.stop();
      throw error;
    }

    done = final.done;
    turn = final.turn;
    lastReply = final.reply;
    addLine(KINDS[kind].label, final.reply);
    if (final.warning) showWarning(final.warning);
    speaking.then(() => { if (run === speechRun) afterSpeaking(); }); // not awaited
  }

  const mic = voice.attachMic($("talk-mic"), {
    language: () => languageCode,
    handsFree,
    onNothingHeard: () => status("I did not hear anything. Press the microphone when you are ready."),
    onText: async (text) => {
      addLine("You", text);
      mic.setEnabled(false);
      status(`The ${KINDS[kind].partner} is thinking…`);
      try {
        await streamTurn(text);
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

  $("talk-repeat").addEventListener("click", async () => {
    if (!lastReply) return;
    await mic.reset(); // in hands-free mode the microphone may already be listening
    say(lastReply);
  });

  $("talk-show-text").addEventListener("change", (event) => {
    $("talk-transcript").hidden = !event.target.checked;
  });

  $("talk-end").addEventListener("click", async () => {
    showError("");
    speechRun += 1; // nothing more is spoken, and the microphone stays off
    voice.stop();
    await mic.reset();
    mic.setEnabled(false);
    setBusy(views.live, "Writing your feedback…");
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
      setBusy(views.live, null);
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
