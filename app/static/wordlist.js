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
    $("wl-download").textContent = finished || rows.length === 0
      ? "⬇ Download CSV"
      : `⬇ Download the first ${rows.length} as CSV`;
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

  $("wl-download").addEventListener("click", () => {
    if (!rows.length) return;
    const lines = [HEADER, ...rows.map(columns)].map((cells) => cells.map(csvField).join(","));
    downloadTextFile("wordlist", createdAt, lines, "csv", "text/csv");
  });

  $("wl-restart").addEventListener("click", () => {
    sessionId = null;
    showError("");
    show("setup");
  });
})();
