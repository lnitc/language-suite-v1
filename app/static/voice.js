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

  // Hands-free: watches the loudness of the microphone and reports when the
  // speaker has finished (a pause after speech), or never started.
  const handsFree = { silenceMs: 2000, giveUpMs: 20000, minimumLevel: 0.02, loudTicks: 2 };

  function watchForSilence(onFinished, onNothingHeard) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass || !stream) return () => {};
    const audio = new AudioContextClass();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const started = Date.now();
    let noise = null;   // loudness of the room: follows the quietest moments
    let loudTicks = 0;
    let spoke = false;
    let quietSince = Date.now();

    const timer = setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) sum += sample * sample;
      const level = Math.sqrt(sum / samples.length);
      const now = Date.now();
      // The room's own noise is the quietest level seen, allowed to creep up
      // slowly. Measuring it this way works even if the learner starts
      // talking at once, which a "listen to the room first" approach gets wrong.
      noise = noise === null || level < noise ? level : noise * 1.005;
      const threshold = Math.max(handsFree.minimumLevel, noise * 3);
      if (level > threshold) {
        loudTicks += 1;
        if (loudTicks >= handsFree.loudTicks) spoke = true; // one click or cough is not speech
        quietSince = now;
      } else {
        loudTicks = 0;
        if (spoke && now - quietSince >= handsFree.silenceMs) onFinished();
        else if (!spoke && now - started >= handsFree.giveUpMs) onNothingHeard();
      }
    }, 100);

    return () => {
      clearInterval(timer);
      audio.close().catch(() => {});
    };
  }

  // Turns a button into a microphone: press to talk, press again to stop.
  // options.language(): language code of the speech.
  // options.onText(text): what to do with the recognised words.
  // options.handsFree(): optional; true makes the recording stop by itself after a pause.
  // options.onNothingHeard(): optional; called when hands-free listening gave up.
  // options.labels: optional; other words on the button for a long recording.
  // options.maxMs(): optional; the recording is stopped by itself after this long.
  // options.onState(state): optional; told when recording starts ("recording"),
  //   when it is being written down ("busy") and when it is over ("idle").
  // options.onRecording(blob): optional; receives the recording itself.
  function attachMic(button, options) {
    let state = "idle";
    let enabled = true;
    let stopWatching = null;
    const labels = {
      idle: "🎤 Speak", recording: "■ Stop", busy: "Listening to your recording…", ...(options.labels || {}),
    };
    let shown = null;
    let limit = null;

    function render() {
      button.textContent = labels[state];
      button.classList.toggle("recording", state === "recording");
      button.disabled = state === "busy" || (!enabled && state === "idle");
      if (state !== shown) {
        shown = state;
        if (state !== "recording") clearTimeout(limit);
        if (options.onState) options.onState(state);
      }
    }

    function endWatching() {
      if (stopWatching) stopWatching();
      stopWatching = null;
    }

    async function begin() {
      stop(); // do not record the teacher's voice
      await startRecording();
      state = "recording";
      render();
      if (options.maxMs) {
        limit = setTimeout(() => { if (state === "recording") run(finish); }, options.maxMs());
      }
      if (options.handsFree && options.handsFree()) {
        stopWatching = watchForSilence(
          () => { if (state === "recording") run(finish); },
          () => { if (state === "recording") run(giveUp); }
        );
      }
    }

    async function finish() {
      endWatching();
      state = "busy";
      render();
      const recording = await stopRecording();
      if (options.onRecording) options.onRecording(recording);
      const text = await transcribe(recording, options.language());
      if (text) await options.onText(text);
      else showError("No words were recognised. Please try again, a little closer to the microphone.");
    }

    async function giveUp() {
      endWatching();
      await stopRecording();
      state = "idle";
      if (options.onNothingHeard) options.onNothingHeard();
    }

    async function run(action) {
      showError("");
      try {
        await action();
      } catch (error) {
        endWatching();
        if (recorder) await stopRecording();
        if (state === "recording") state = "idle";
        showError(error.message);
      } finally {
        if (state === "busy") state = "idle";
        render();
      }
    }

    button.addEventListener("click", () => {
      if (state === "idle") run(begin);
      else if (state === "recording") run(finish);
    });

    render();
    return {
      setEnabled(value) { enabled = value; render(); },
      // Starts listening without a click (hands-free mode).
      start() { if (state === "idle" && enabled) run(begin); },
      async reset() {
        endWatching();
        if (recorder) await stopRecording();
        state = "idle";
        render();
      },
    };
  }

  if ("speechSynthesis" in window) window.speechSynthesis.getVoices(); // start loading the list

  return { speak, stop, fillSelect, attachMic, handsFree };
})();
