"use strict";
// History and mistake review. Uses helpers from common.js.
// The data lives in a database file on this computer (app/features/history.py).

(() => {
  const FEATURES = {
    conversation: "Conversation",
    interview: "Job interview",
    interpreter: "Interpreter",
    speech: "Speech",
    shadowing: "Shadowing",
    listening: "Listening comprehension",
    vocabulary: "Vocabulary practice",
    dictation: "Dictation",
    essay: "Essay",
    translation: "Translation",
    reading: "Reading comprehension",
    grammar: "Grammar drills",
  };
  const PAGE = 50;
  const label = (feature) => FEATURES[feature] || feature;
  const when = (iso) => {
    const stamp = dateStamp(new Date(iso));
    return `${stamp.day} ${stamp.time}`;
  };
  const percent = (value) => (value === null ? "-" : `${value}%`);
  const trim = (n) => String(Math.round(n * 10) / 10);

  function cell(row, text) {
    const td = document.createElement("td");
    td.textContent = text; // textContent: stored text is never run as HTML
    row.appendChild(td);
    return td;
  }

  function button(text, onClick) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = text;
    el.addEventListener("click", onClick);
    return el;
  }

  // Keeps the chosen value of a filter while its options are rebuilt.
  function fillSelect(select, values, allLabel, names = (value) => value) {
    const chosen = select.value;
    select.replaceChildren(new Option(allLabel, ""), ...values.map((value) => new Option(names(value), value)));
    select.value = values.includes(chosen) ? chosen : "";
  }

  async function run(work) {
    showError("");
    try {
      await work();
    } catch (error) {
      showError(error.message);
    }
  }

  // ---------- history ----------

  let shown = PAGE;  // how many results are listed
  let opened = null; // the result shown in full

  $("hist-on").checked = historyIsOn();
  $("hist-on").addEventListener("change", (event) => {
    try {
      localStorage.setItem("language-suite-history", event.target.checked ? "on" : "off");
    } catch { /* without storage the history simply stays on */ }
  });

  async function loadHistory() {
    const query = new URLSearchParams({ limit: String(shown) });
    if ($("hist-language").value) query.set("language", $("hist-language").value);
    if ($("hist-feature").value) query.set("feature", $("hist-feature").value);
    const data = await api(`/api/history/results?${query}`);
    fillSelect($("hist-language"), data.languages, "All languages");
    fillSelect($("hist-feature"), data.features, "All activities", label);

    const summary = $("hist-summary").tBodies[0];
    summary.replaceChildren();
    for (const row of data.summary) {
      const tr = document.createElement("tr");
      cell(tr, label(row.feature));
      cell(tr, String(row.sessions));
      cell(tr, row.average === null ? "not scored" : percent(row.average));
      cell(tr, percent(row.recent_average));
      cell(tr, when(row.latest));
      summary.appendChild(tr);
    }

    const table = $("hist-table").tBodies[0];
    table.replaceChildren();
    for (const row of data.results) {
      const tr = document.createElement("tr");
      cell(tr, when(row.created_at));
      cell(tr, label(row.feature));
      cell(tr, row.language);
      cell(tr, row.title);
      cell(tr, row.percent === null ? "-" : `${trim(row.score)} / ${trim(row.total)} (${row.percent}%)`);
      cell(tr, "").append(button("Open", () => run(() => openResult(row.id))));
      table.appendChild(tr);
    }

    const any = data.results.length > 0;
    $("hist-empty").hidden = any;
    $("hist-summary").hidden = !any;
    $("hist-table").hidden = !any;
    $("hist-count").textContent = any
      ? `Sessions (${data.results.length < data.count ? `${data.results.length} of ${data.count}` : data.count})`
      : "";
    $("hist-more").hidden = data.results.length >= data.count;
    $("hist-clear").hidden = !any;
  }

  function showHistoryList() {
    opened = null;
    $("hist-detail").hidden = true;
    $("hist-list").hidden = false;
    return loadHistory();
  }

  async function openResult(id) {
    opened = await api(`/api/history/results/${id}`);
    $("hist-detail-title").textContent = `${label(opened.feature)} · ${when(opened.created_at)}`;
    $("hist-report").textContent = opened.report;
    $("hist-list").hidden = true;
    $("hist-detail").hidden = false;
    window.scrollTo(0, 0);
  }

  $("hist-language").addEventListener("change", () => { shown = PAGE; run(loadHistory); });
  $("hist-feature").addEventListener("change", () => { shown = PAGE; run(loadHistory); });
  $("hist-more").addEventListener("click", () => { shown += PAGE; run(loadHistory); });
  $("hist-back").addEventListener("click", () => run(showHistoryList));
  $("hist-download").addEventListener("click", () => {
    if (opened) downloadTextFile(opened.feature, new Date(opened.created_at), opened.report.split("\n"));
  });
  $("hist-delete").addEventListener("click", () => run(async () => {
    if (!opened || !window.confirm("Delete this result from the history?")) return;
    await api(`/api/history/results/${opened.id}`, { method: "DELETE" });
    await showHistoryList();
  }));
  $("hist-clear").addEventListener("click", () => run(async () => {
    if (!window.confirm("Delete every saved result? Your list of mistakes is kept. This cannot be undone.")) return;
    await api("/api/history/results", { method: "DELETE" });
    await loadHistory();
  }));

  // ---------- my mistakes ----------

  let mistakes = [];

  // Words that Vocabulary practice can ask again: not yet learned, and saved
  // with their accepted translations. One language pair at a time.
  function practisable() {
    const words = mistakes.filter((row) =>
      row.feature === "vocabulary" && !row.learned && Array.isArray(row.extra.translations) && row.extra.source_language);
    if (!words.length) return [];
    const same = (row) => row.language === words[0].language && row.extra.source_language === words[0].extra.source_language;
    return words.filter(same).slice(0, 50);
  }

  function mistakeLine(className, title, text) {
    const p = document.createElement("p");
    p.className = className;
    if (title) {
      const strong = document.createElement("strong");
      strong.textContent = `${title} `;
      p.appendChild(strong);
    }
    p.append(text);
    return p;
  }

  async function loadMistakes() {
    const query = new URLSearchParams();
    if ($("mist-language").value) query.set("language", $("mist-language").value);
    if ($("mist-feature").value) query.set("feature", $("mist-feature").value);
    if ($("mist-show").value) query.set("learned", $("mist-show").value);
    const data = await api(`/api/history/mistakes?${query}`);
    mistakes = data.mistakes;
    fillSelect($("mist-language"), data.languages, "All languages");
    fillSelect($("mist-feature"), data.features, "All activities", label);

    const container = $("mist-items");
    container.replaceChildren();
    for (const row of mistakes) {
      const box = document.createElement("div");
      box.className = `mistake${row.learned ? " learned" : ""}`;
      box.appendChild(mistakeLine("prompt", "", row.prompt));
      if (row.your_answer && row.your_answer !== row.prompt) box.appendChild(mistakeLine("yours", "You:", row.your_answer));
      if (row.correct) box.appendChild(mistakeLine("right", "Correct:", row.correct));
      if (row.note) box.appendChild(mistakeLine("", "", row.note));
      box.appendChild(mistakeLine(
        "muted", "",
        `${label(row.feature)} · ${row.language} · ${when(row.updated_at)}` +
          (row.times > 1 ? ` · wrong ${row.times} times` : "") + (row.learned ? " · learned" : "")
      ));
      const tools = document.createElement("div");
      tools.className = "player";
      tools.append(
        button(row.learned ? "Review again" : "Mark as learned", () => run(async () => {
          await api(`/api/history/mistakes/${row.id}`, { method: "PATCH", body: JSON.stringify({ learned: !row.learned }) });
          await loadMistakes();
        })),
        button("Remove", () => run(async () => {
          await api(`/api/history/mistakes/${row.id}`, { method: "DELETE" });
          await loadMistakes();
        }))
      );
      box.appendChild(tools);
      container.appendChild(box);
    }

    $("mist-count").textContent = mistakes.length
      ? `${data.count} ${data.count === 1 ? "entry" : "entries"}${mistakes.length < data.count ? ` (showing the latest ${mistakes.length})` : ""}`
      : "Nothing to show. Mistakes from your sessions are collected here.";
    const words = practisable();
    $("mist-practise").disabled = !words.length;
    $("mist-download").disabled = !mistakes.length;
    $("mist-practise-note").textContent = words.length
      ? `${words.length} ${words.length === 1 ? "word" : "words"} (${words[0].extra.source_language} → ${words[0].language}) can be practised again.`
      : "";
  }

  for (const id of ["mist-language", "mist-feature", "mist-show"]) {
    $(id).addEventListener("change", () => run(loadMistakes));
  }

  $("mist-practise").addEventListener("click", () => {
    const words = practisable();
    if (!words.length) return;
    const tab = document.querySelector('.tab[data-feature="vocabulary"]');
    lastOpened.vocabulary = tab;
    openSection("vocabulary");
    document.dispatchEvent(new CustomEvent("practise-words", {
      detail: {
        source: words[0].extra.source_language,
        target: words[0].language,
        codes: words[0].extra.codes,
        words: words.map((row) => ({ word: row.prompt, translations: row.extra.translations.slice(0, 10) })),
      },
    }));
  });

  $("mist-download").addEventListener("click", () => {
    const now = new Date();
    const stamp = dateStamp(now);
    const lines = ["Language Suite: My mistakes", `Date: ${stamp.day} ${stamp.time}`, `Entries: ${mistakes.length}`];
    mistakes.forEach((row, i) => {
      lines.push("", `${i + 1}. ${row.prompt}`);
      if (row.your_answer && row.your_answer !== row.prompt) lines.push(`   You: ${row.your_answer}`);
      if (row.correct) lines.push(`   Correct: ${row.correct}`);
      if (row.note) lines.push(`   ${row.note}`);
      lines.push(`   ${label(row.feature)}, ${row.language}, ${when(row.updated_at)}${row.times > 1 ? `, wrong ${row.times} times` : ""}${row.learned ? ", learned" : ""}`);
    });
    lines.push("");
    downloadTextFile("mistakes", now, lines);
  });

  $("mist-clear-learned").addEventListener("click", () => run(async () => {
    if (!window.confirm("Remove every entry that is marked as learned?")) return;
    await api("/api/history/mistakes?learned=true", { method: "DELETE" });
    await loadMistakes();
  }));

  // Fresh data every time one of the two pages is opened.
  document.addEventListener("feature-change", (event) => {
    if (event.detail.feature === "history") run(showHistoryList);
    if (event.detail.feature === "mistakes") run(loadMistakes);
  });
})();
