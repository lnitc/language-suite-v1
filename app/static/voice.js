"use strict";
// Shared voice tools: the mouth (speak text) and the ear (record and transcribe).
// Uses helpers from common.js.

const voice = (() => {
  let ttsMode = "browser"; // "browser" voices, or "server" when a speech server is set
  const audioCache = new Map(); // text -> object URL (server mode)
  const player = new Audio();
  let finishCurrent = null;

  api("/api/health")
    .then((info) => { ttsMode = info.tts_provider === "browser" ? "browser" : "server"; })
    .catch(() => {});

  // ---------- mouth ----------

  const primary = (code) => (code || "").split(/[-_]/)[0].toLowerCase();

  function voicesFor(code) {
    if (!("speechSynthesis" in window)) return [];
    const all = window.speechSynthesis.getVoices();
    return primary(code) ? all.filter((v) => primary(v.lang) === primary(code)) : all;
  }

  function remembered(code) {
    try { return localStorage.getItem(`voice-${primary(code)}`) || ""; } catch { return ""; }
  }

  function pickVoice(code) {
    const voices = voicesFor(code);
    return voices.find((v) => v.name === remembered(code)) || voices[0] || null;
  }

  // Fills a <select> with the voices for a language and remembers the choice.
  function fillSelect(select, label, code) {
    const voices = ttsMode === "browser" ? voicesFor(code) : [];
    select.replaceChildren();
    for (const v of voices) {
      const option = document.createElement("option");
      option.value = v.name;
      option.textContent = `${v.name} (${v.lang})`;
      select.appendChild(option);
    }
    const chosen = pickVoice(code);
    if (chosen) select.value = chosen.name;
    label.hidden = voices.length === 0;
    select.onchange = () => {
      try { localStorage.setItem(`voice-${primary(code)}`, select.value); } catch { /* optional */ }
    };
  }

  function stop() {
    player.pause();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (finishCurrent) finishCurrent();
  }

  function speakInBrowser(text, code, rate) {
    return new Promise((resolve, reject) => {
      if (!("speechSynthesis" in window)) {
        reject(new Error("This browser cannot speak text. Try Chrome or Edge, or use a speech server."));
        return;
      }
      const chosen = pickVoice(code);
      if (!chosen && primary(code) && window.speechSynthesis.getVoices().length > 0) {
        reject(new Error(
          `This browser has no voice for this language (${code}). ` +
          'Add one in Windows (see "Voices" in the README), or use a speech server.'
        ));
        return;
      }
      const utterance = new SpeechSynthesisUtterance(text);
      if (chosen) utterance.voice = chosen;
      utterance.lang = chosen ? chosen.lang : code || "";
      utterance.rate = rate;
      // Safety net: some browsers never report the end of speech. Without it
      // the microphone would stay locked.
      const longest = Math.min(90000, 4000 + (text.length * 150) / rate);
      const watchdog = setTimeout(() => done(), longest);
      const done = () => {
        clearTimeout(watchdog);
        if (finishCurrent === done) finishCurrent = null;
        resolve();
      };
      utterance.onend = done;
      utterance.onerror = done;
      finishCurrent = done;
      window.speechSynthesis.speak(utterance);
    });
  }

  async function speakFromServer(text, code, rate) {
    if (!audioCache.has(text)) {
      const response = await request("/api/speech/synthesize", {
        method: "POST",
        body: JSON.stringify({ text, language_code: code || "" }),
      });
      audioCache.set(text, URL.createObjectURL(await response.blob()));
    }
    return new Promise((resolve, reject) => {
      const done = () => {
        if (finishCurrent === done) finishCurrent = null;
        resolve();
      };
      player.onended = done;
      player.onerror = done;
      finishCurrent = done;
      player.src = audioCache.get(text);
      player.playbackRate = rate;
      player.play().catch((error) => { done(); reject(error); });
    });
  }

  // Speaks the text and resolves when it has finished (or was stopped).
  function speak(text, code, rate = 1) {
    stop();
    return ttsMode === "browser"
      ? speakInBrowser(text, code, rate)
      : speakFromServer(text, code, rate);
  }

  // ---------- ear ----------

  let recorder = null;
  let stream = null;
  let chunks = [];

  async function startRecording() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      throw new Error("This browser cannot record audio. Try a current Chrome or Edge.");
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      throw new Error("The microphone is blocked or missing. Allow microphone access for this page and try again.");
    }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.start();
  }

  function releaseMicrophone() {
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
  }

  function stopRecording() {
    return new Promise((resolve) => {
      if (!recorder || recorder.state === "inactive") {
        releaseMicrophone();
        resolve(new Blob(chunks));
        return;
      }
      const type = recorder.mimeType || "audio/webm";
      recorder.onstop = () => {
        releaseMicrophone();
        resolve(new Blob(chunks, { type }));
      };
      recorder.stop();
    });
  }

  async function transcribe(blob, code) {
    const response = await request(
      `/api/speech/transcribe?language=${encodeURIComponent(code || "")}`,
      {
        method: "POST",
        headers: { "Content-Type": (blob.type || "audio/webm").split(";")[0] },
        body: blob,
      }
    );
    return (await response.json()).text;
  }

  // Turns a button into a microphone: press to talk, press again to stop.
  // options.language(): language code of the speech; options.onText(text): what to do with it.
  function attachMic(button, options) {
    let state = "idle";
    let enabled = true;
    const labels = { idle: "🎤 Speak", recording: "■ Stop", busy: "Listening to your recording…" };

    function render() {
      button.textContent = labels[state];
      button.classList.toggle("recording", state === "recording");
      button.disabled = state === "busy" || (!enabled && state === "idle");
    }

    button.addEventListener("click", async () => {
      showError("");
      try {
        if (state === "idle") {
          stop(); // do not record the teacher's voice
          await startRecording();
          state = "recording";
          render();
        } else if (state === "recording") {
          state = "busy";
          render();
          const text = await transcribe(await stopRecording(), options.language());
          if (text) await options.onText(text);
          else showError("No words were recognised. Please try again, a little closer to the microphone.");
        }
      } catch (error) {
        if (recorder) await stopRecording();
        showError(error.message);
      } finally {
        if (state === "busy") state = "idle";
        render();
      }
    });

    render();
    return {
      setEnabled(value) { enabled = value; render(); },
      async reset() {
        if (recorder) await stopRecording();
        state = "idle";
        render();
      },
    };
  }

  if ("speechSynthesis" in window) window.speechSynthesis.getVoices(); // start loading the list

  return { speak, stop, fillSelect, attachMic };
})();
