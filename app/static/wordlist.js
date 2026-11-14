"use strict";
// Feature 6: vocabulary list creator. Uses helpers from common.js.

(() => {
  const views = { setup: $("wl-setup"), list: $("wl-list") };
  const HEADER = ["Word", "Pronunciation", "Translation", "Example and notes"];

  let sessionId = null;
  let plan = null; // { total, batch_size, batch_count }
  let rows = [];
  let nextBatch = 0;
  let running = false;
  let stopRequested = false;
  let createdAt = null;
  let languages = { source: "", target: "" };

  const FORMATS = { csv: "CSV", txt: "text", docx: "Word", pdf: "PDF", json: "JSON" };
  try { // the format chosen last time is offered again
    const saved = localStorage.getItem("wordlist-format");
    if (saved in FORMATS) $("wl-format").value = saved;
  } catch { /* remembering the format is optional */ }

  function show(name) {
    for (const [key, el] of Object.entries(views)) el.hidden = key !== name;
  }

  function status(text) { $("wl-status").textContent = text; }

  // Column 4: the example with its translation, then any remarks.
  function exampleAndNotes(row) {
    const example = [row.example, row.example_translation].filter(Boolean).join(" — ");
    return [example, row.remarks].filter(Boolean).join(" | ");
  }

  function columns(row) {
    return [row.word, row.pronunciation, row.translation, exampleAndNotes(row)];
  }

  function addRows(batch) {
    const body = $("wl-rows");
    for (const row of batch) {
      rows.push(row);
      const tr = document.createElement("tr");
      if (!row.complete) tr.className = "incomplete";
      for (const text of [String(rows.length), ...columns(row)]) {
        const td = document.createElement("td");
        td.textContent = text; // textContent: model output is never run as HTML
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }

  function setButtons() {
    const finished = nextBatch >= plan.batch_count;
    $("wl-download").disabled = running || rows.length === 0;
    const format = FORMATS[$("wl-format").value];
    $("wl-download").textContent = finished || rows.length === 0
      ? `⬇ Download as ${format}`
      : `⬇ Download the first ${rows.length} as ${format}`;
    $("wl-continue").hidden = running || finished;
    $("wl-stop").hidden = !running;
    $("wl-restart").disabled = running;
  }

  // Asks for one batch after another, so the list fills in as it is made.
  async function run() {
    running = true;
    stopRequested = false;
    showError("");
    setButtons();
    try {
      while (nextBatch < plan.batch_count && !stopRequested) {
        const first = nextBatch * plan.batch_size + 1;
        const last = Math.min(plan.total, first + plan.batch_size - 1);
        status(`Preparing entries ${first} to ${last} of ${plan.total}…`);
        const batch = await api(`/api/wordlist/sessions/${sessionId}/batches/${nextBatch}`, { method: "POST" });
        addRows(batch.rows);
        nextBatch += 1;
        $("wl-progress").value = rows.length;
      }
      if (nextBatch >= plan.batch_count) {
        const incomplete = rows.filter((row) => !row.complete).length;
        status(
          `Done: ${rows.length} entries.` +
          (incomplete ? ` ${incomplete} could not be completed (shown in colour); check them by hand.` : "")
        );
        $("wl-progress").hidden = true;
      } else {
        status(`Stopped after ${rows.length} of ${plan.total} entries. Press Continue to go on.`);
      }
    } catch (error) {
      showError(error.message);
      status(`Stopped after ${rows.length} of ${plan.total} entries. Press Continue to try again.`);
    } finally {
      running = false;
      setButtons();
    }
  }

  // One CSV field, quoted where the format requires it.
  function csvField(value) {
    let text = String(value ?? "");
    // Spreadsheets treat a leading = or @ as a formula; a leading apostrophe keeps it as text.
    if (/^[=@]/.test(text)) text = `'${text}`;
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  $("wl-file").addEventListener("change", () => {
    const chosen = $("wl-file").files.length > 0;
    $("wl-count").disabled = chosen;
    showNote(
      "wl-file-note",
      chosen ? 'Your own list will be used: every word in it is returned (up to 100), and "Number of words" is ignored.' : ""
    );
  });

  $("wl-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    const button = $("wl-start");
    button.disabled = true;
    button.textContent = "Getting the words ready…";
    try {
      const { text: material } = await readMaterial($("wl-file").files[0], { warnWhenLong: false });
      const started = await api("/api/wordlist/sessions", {
        method: "POST",
        body: JSON.stringify({
          source_language: $("wl-source").value.trim(),
          target_language: $("wl-target").value.trim(),
          difficulty: $("wl-difficulty").value,
          count: Number($("wl-count").value) || 20,
          prompt: $("wl-prompt").value,
          material,
        }),
      });
      sessionId = started.session_id;
      plan = started;
      rows = [];
      nextBatch = 0;
      createdAt = new Date();
      languages = { source: $("wl-source").value.trim(), target: $("wl-target").value.trim() };
      $("wl-rows").replaceChildren();
      $("wl-progress").max = plan.total;
      $("wl-progress").value = 0;
      $("wl-progress").hidden = false;
      showNote(
        "wl-warning",
        started.provided > started.limit
          ? `Your file has ${started.provided} entries. Only the first ${started.limit} are used; ` +
            "split the file to do the rest."
          : !started.from_file && started.total < Number($("wl-count").value)
            ? `The model proposed ${started.total} words instead of ${$("wl-count").value}.`
            : ""
      );
      show("list");
      run();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "Create list";
    }
  });

  $("wl-continue").addEventListener("click", run);
  $("wl-stop").addEventListener("click", () => {
    stopRequested = true;
    status("Stopping after the entries now being prepared…");
    $("wl-stop").hidden = true;
  });

  // ---------- downloads: the same list in any format, as often as wanted ----------

  const title = () => `Vocabulary list: ${languages.source}`;
  const subtitle = () => {
    const stamp = dateStamp(createdAt);
    return `${languages.source} with explanations in ${languages.target} · ${rows.length} entries · ${stamp.day}`;
  };

  function downloadCsv() {
    const lines = [HEADER, ...rows.map(columns)].map((cells) => cells.map(csvField).join(","));
    downloadTextFile("wordlist", createdAt, lines, "csv", "text/csv");
  }

  function downloadText() {
    const lines = [title(), subtitle(), ""];
    rows.forEach((row, i) => {
      lines.push(`${i + 1}. ${row.word}${row.pronunciation ? `  [${row.pronunciation}]` : ""}`);
      if (row.translation) lines.push(`   ${row.translation}`);
      if (row.example) lines.push(`   Example: ${row.example}`);
      if (row.example_translation) lines.push(`            ${row.example_translation}`);
      if (row.remarks) lines.push(`   Note: ${row.remarks}`);
      lines.push("");
    });
    downloadTextFile("wordlist", createdAt, lines);
  }

  // JSON keeps the example, its translation and the remarks as separate fields.
  function downloadJson() {
    const data = {
      source_language: languages.source,
      target_language: languages.target,
      created: createdAt.toISOString(),
      entries: rows.map((row) => ({
        word: row.word,
        pronunciation: row.pronunciation,
        translation: row.translation,
        example: row.example,
        example_translation: row.example_translation,
        remarks: row.remarks,
      })),
    };
    // No UTF-8 marker: many JSON readers reject it.
    downloadTextFile("wordlist", createdAt, [JSON.stringify(data, null, 2)], "json", "application/json", false);
  }

  // A Word file is a zipped package, so the app server builds it from the rows.
  async function downloadDocx() {
    const response = await request("/api/wordlist/export/docx", {
      method: "POST",
      body: JSON.stringify({
        title: title(),
        subtitle: subtitle(),
        header: ["#", ...HEADER],
        rows: rows.map((row, i) => [String(i + 1), ...columns(row)]),
      }),
    });
    downloadBlob(await response.blob(), fileName("wordlist", createdAt, "docx"));
  }

  // PDF: the browser's own "Save as PDF" is used, because it can draw every
  // script (kana, kanji, Cyrillic, Arabic, phonetic symbols) with the fonts
  // already on the computer. A PDF built by the app would need its own fonts.
  function printAsPdf() {
    const area = $("print-area");
    area.replaceChildren();
    const heading = document.createElement("h1");
    heading.textContent = title();
    const info = document.createElement("p");
    info.textContent = subtitle();
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const text of ["#", ...HEADER]) {
      const th = document.createElement("th");
      th.textContent = text;
      head.appendChild(th);
    }
    const body = table.createTBody();
    rows.forEach((row, i) => {
      const tr = body.insertRow();
      for (const text of [String(i + 1), ...columns(row)]) tr.insertCell().textContent = text;
    });
    area.append(heading, info, table);

    // The page title becomes the suggested file name in the Save dialog.
    const pageTitle = document.title;
    document.title = fileName("wordlist", createdAt, "");
    window.addEventListener("afterprint", () => {
      document.title = pageTitle;
      area.replaceChildren();
    }, { once: true });
    window.print();
  }

  $("wl-format").addEventListener("change", () => {
    try { localStorage.setItem("wordlist-format", $("wl-format").value); } catch { /* optional */ }
    showNote(
      "wl-format-note",
      $("wl-format").value === "pdf"
        ? 'PDF opens the print window: choose "Save as PDF" (or "Microsoft Print to PDF") as the printer, then Save.'
        : ""
    );
    if (plan) setButtons();
  });

  $("wl-download").addEventListener("click", async () => {
    if (!rows.length) return;
    showError("");
    const button = $("wl-download");
    button.disabled = true;
    try {
      const format = $("wl-format").value;
      if (format === "txt") downloadText();
      else if (format === "json") downloadJson();
      else if (format === "docx") await downloadDocx();
      else if (format === "pdf") printAsPdf();
      else downloadCsv();
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
    }
  });

  $("wl-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });

  $("wl-format").dispatchEvent(new Event("change")); // show the hint for a remembered format
})();
