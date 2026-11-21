// SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
// The transcript editor: turns, speakers, the player, Follow, select-and-listen, editing,
// undo and redo, and autosave. The transcript lives here, in `model`; the screen is
// rendered from it. Word objects are never changed in place (edits make new arrays), so
// an undo snapshot can share them.
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const editor = $("#editor");
  if (!editor) return;
  const { splitWords, retime } = window.wmRetime;

  const data = JSON.parse($("#transcript-data").textContent);
  const model = {
    speakers: data.speakers.slice(),
    names: { ...data.names },
    turns: data.turns.map((t) => ({
      speaker: t.speaker,
      words: t.words.map(([text, start, end]) => ({ text, start, end })),
    })),
  };
  const duration = data.duration;

  const audio = $("#audio");
  const turnsEl = $("#turns");
  const scroller = $("#ed-scroll");
  const player = $(".player");
  const note = $("#audio-note");
  const pop = $("#sel-pop");
  const menu = $("#spk-menu");

  // ---- helpers ------------------------------------------------------------------------------
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const pad = (n) => String(n).padStart(2, "0");
  // 08:54, 1:02:03, or with tenths: 10:05.1
  function clock(seconds, tenths = false) {
    const total = Math.max(0, Math.round(seconds * (tenths ? 10 : 1)));
    const whole = tenths ? Math.floor(total / 10) : total;
    const h = Math.floor(whole / 3600);
    const m = Math.floor((whole % 3600) / 60);
    let s = pad(whole % 60);
    if (tenths) s += "." + (total % 10);
    return h ? `${h}:${pad(m)}:${s}` : `${pad(m)}:${s}`;
  }
  // A speaker keeps its colour: it follows the number in its id (SPEAKER_02 -> the third
  // colour), so merging one speaker away doesn't recolour the others.
  function speakerColour(id) {
    const n = /(\d+)$/.exec(id);
    const k = n ? Number(n[1]) : Math.max(0, model.speakers.indexOf(id));
    return `var(--spk-${(k % 6) + 1})`;
  }
  const speakerName = (id) => model.names[id] || id;
  const typing = (target) => target.closest?.("input, textarea, select, [contenteditable]");
  const nonSpace = (text) => text.replace(/\s+/g, "").length;
  const turnStart = (turn) => (turn.words.length ? turn.words[0].start : null);
  const turnEnd = (turn) => (turn.words.length ? turn.words[turn.words.length - 1].end : null);
  const turnIndex = (node) => [...turnsEl.children].indexOf(node.closest(".turn"));
  const textOf = (ti) => turnsEl.children[ti]?.querySelector(".turn-text");

  // The time a turn's words may use: from the end of the turn before to the start of the next.
  function window_(ti) {
    let t0 = 0;
    for (let k = ti - 1; k >= 0; k--) {
      const e = turnEnd(model.turns[k]);
      if (e !== null) { t0 = e; break; }
    }
    let t1 = duration;
    for (let k = ti + 1; k < model.turns.length; k++) {
      const s = turnStart(model.turns[k]);
      if (s !== null) { t1 = s; break; }
    }
    const own = model.turns[ti].words;
    if (own.length) {
      t0 = Math.min(t0, own[0].start);
      t1 = Math.max(t1, own[own.length - 1].end);
    }
    return [t0, t1];
  }

  // ---- caret positions, counted in non-space characters (they survive re-rendering) ----------
  function nsBefore(p, node, offset) {
    const r = document.createRange();
    r.selectNodeContents(p);
    r.setEnd(node, offset);
    return nonSpace(r.toString());
  }
  function caretState() {
    const sel = window.getSelection();
    if (!sel.rangeCount || !sel.isCollapsed) return null;
    const p = sel.focusNode && (sel.focusNode.nodeType === 1 ? sel.focusNode : sel.focusNode.parentElement)?.closest(".turn-text");
    if (!p || !turnsEl.contains(p)) return null;
    const r = document.createRange();
    r.selectNodeContents(p);
    r.setEnd(sel.focusNode, sel.focusOffset);
    const before = r.toString();
    return { turn: turnIndex(p), ns: nonSpace(before), space: /\s$/.test(before) };
  }
  // Put the caret after `ns` non-space characters of `p` (and past the space after them,
  // if `space` and there still is one).
  function placeCaret(p, ns, space = false) {
    p.focus({ preventScroll: true });
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let count = 0;
    let node;
    let target = null;
    let at = 0;
    outer: while ((node = walker.nextNode())) {
      const t = node.data;
      for (let i = 0; i <= t.length; i++) {
        if (count === ns) {
          const afterSpace = i > 0 && /\s/.test(t[i - 1]);
          if (!target || afterSpace) {
            target = node;
            at = i;
          }
          if (!space || afterSpace) break outer;
        }
        if (i < t.length && !/\s/.test(t[i]) && ++count > ns) break outer;
      }
    }
    const r = document.createRange();
    if (target) r.setStart(target, at);
    else r.selectNodeContents(p);
    r.collapse(!!target);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  }
  function restoreCaret(c) {
    if (!c) return;
    const p = textOf(Math.min(c.turn, model.turns.length - 1));
    if (p) placeCaret(p, c.ns, c.space);
  }
  // Which word of a turn a non-space offset falls in (the word before, at a boundary).
  function wordAtNs(turn, ns) {
    let cum = 0;
    for (let i = 0; i < turn.words.length; i++) {
      cum += nonSpace(turn.words[i].text);
      if (ns < cum) return i;
    }
    return turn.words.length - 1;
  }

  // ---- rendering ----------------------------------------------------------------------------
  // `flat` lists every word in reading order for Follow; `el` is null while a turn is being
  // typed in and its word elements are stale.
  let flat = [];
  const dirty = new Set(); // turns whose word elements are stale
  const editBase = new Map(); // turn -> its words before the current run of typing

  const CHEV = '<svg class="i" width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg>';

  function fillText(p, turn) {
    const frag = document.createDocumentFragment();
    turn.words.forEach((w, wi) => {
      if (wi) frag.append(" ");
      frag.append(el("span", "w", w.text));
    });
    p.replaceChildren(frag);
  }

  function renderTurn(turn) {
    const div = el("div", "turn");
    div.style.setProperty("--spk", speakerColour(turn.speaker));
    const start = turnStart(turn) ?? 0;
    const time = el("button", "turn-time", clock(start));
    time.type = "button";
    time.title = "Play from here";
    const who = el("button", "turn-speaker");
    who.type = "button";
    who.setAttribute("aria-haspopup", "menu");
    who.title = "Change speaker (Alt+↑/↓)";
    who.append(el("span", "", speakerName(turn.speaker)));
    who.insertAdjacentHTML("beforeend", CHEV);
    const text = el("p", "turn-text");
    text.contentEditable = "plaintext-only";
    text.spellcheck = false;
    text.setAttribute("aria-label", `${speakerName(turn.speaker)} at ${clock(start)}`);
    fillText(text, turn);
    div.append(time, who, text);
    return div;
  }

  function renderTurns() {
    const frag = document.createDocumentFragment();
    for (const turn of model.turns) frag.append(renderTurn(turn));
    turnsEl.replaceChildren(frag);
    if (typeof clearVirtual === "function" && virtual) clearVirtual();
    dirty.clear();
    editBase.clear();
    reindex();
  }

  function reindex() {
    flat = [];
    model.turns.forEach((turn, ti) => {
      const p = textOf(ti);
      const spans = !dirty.has(ti) && p ? p.querySelectorAll(".w") : [];
      const ok = spans.length === turn.words.length;
      turn.words.forEach((w, wi) => {
        flat.push({ start: w.start, end: w.end, el: ok ? spans[wi] : null, turn: ti });
      });
    });
    spokenIndex = -1;
    playingTurn = -1;
    update();
    if (typeof search === "function" && findInput.value) search();
  }

  function renderSpeakers() {
    const stats = new Map(model.speakers.map((s) => [s, { turns: 0, time: 0, longest: null }]));
    let total = 0;
    for (const turn of model.turns) {
      const st = stats.get(turn.speaker);
      if (!st || !turn.words.length) continue;
      const len = turnEnd(turn) - turnStart(turn);
      st.turns += 1;
      st.time += len;
      total += len;
      if (!st.longest || len > st.longest.len) st.longest = { start: turnStart(turn), len };
    }
    const used = model.speakers.filter((sp) => stats.get(sp).turns).length;
    $("#speaker-count").textContent = `${used} speaker${used === 1 ? "" : "s"}`;
    const list = $("#speaker-list");
    list.replaceChildren(
      ...model.speakers
        .filter((s) => stats.get(s).turns)
        .map((s) => {
          const st = stats.get(s);
          const pct = total ? Math.round((st.time / total) * 100) : 0;
          const card = el("div", "spk-card");
          card.style.setProperty("--spk", speakerColour(s));
          const row = el("div", "spk-row");
          const play = el("button", "btn btn-secondary btn-sm");
          play.type = "button";
          play.dataset.sample = s;
          play.innerHTML = '<svg class="i i-fill" width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3l8 5-8 5z"/></svg>';
          play.append(" Play sample");
          play.disabled = !audioReady;
          const merge = el("button", "btn btn-ghost btn-sm spk-merge", "Merge into…");
          merge.type = "button";
          merge.dataset.merge = s;
          merge.setAttribute("aria-haspopup", "menu");
          merge.disabled = used < 2;
          merge.title = "Move all of this speaker's turns to another speaker";
          row.append(play, merge);
          const bar = el("div", "spk-bar");
          const fill = el("span");
          fill.style.width = `${pct}%`;
          bar.append(fill);
          const foot = el("div", "spk-foot");
          foot.append(bar, el("span", "spk-stats", `${st.turns} turn${st.turns === 1 ? "" : "s"} · ${pct}%`));
          const head = el("label", "spk-name");
          const name = el("input", "spk-input");
          name.type = "text";
          name.value = model.names[s] || "";
          name.placeholder = s;
          name.dataset.speaker = s;
          name.autocomplete = "off";
          name.spellcheck = false;
          name.setAttribute("aria-label", `Name for ${s}`);
          head.append(name);
          card.append(head, row, foot);
          card._sample = st.longest;
          return card;
        }),
    );
  }

  function renderTimeline() {
    const segs = [];
    for (const turn of model.turns) {
      if (!turn.words.length) continue;
      const start = turnStart(turn);
      const end = turnEnd(turn);
      const last = segs[segs.length - 1];
      if (last && last.speaker === turn.speaker && start - last.end < 2) last.end = end;
      else segs.push({ speaker: turn.speaker, start, end });
    }
    $("#tl-segs").replaceChildren(
      ...segs.map((s) => {
        const span = el("span");
        span.style.left = `${(s.start / duration) * 100}%`;
        span.style.width = `max(2px, ${((s.end - s.start) / duration) * 100}%)`;
        span.style.setProperty("--spk", speakerColour(s.speaker));
        return span;
      }),
    );
  }

  function renderAll(caret = caretState()) {
    renderTurns();
    renderSpeakers();
    renderTimeline();
    restoreCaret(caret);
  }

  // ---- audio --------------------------------------------------------------------------------
  let audioReady = false;
  let rate = 1;
  let range = null; // {start, end, loop, slow} while a selection or sample is playing

  function setNote(text, error = false) {
    note.textContent = text;
    note.classList.toggle("is-error", error);
  }

  async function loadAudio() {
    if (data.audio_problem) {
      setNote(data.audio_problem, true); // loading audio would crash the window
      return;
    }
    try {
      const resp = await fetch(`/jobs/${data.job}/audio/state`);
      if (!resp.ok) throw new Error(resp.statusText);
      const st = await resp.json();
      if (st.state === "ready") {
        setNote("");
        audio.src = `/jobs/${data.job}/audio?v=${st.version}`;
      } else if (st.state === "making") {
        setNote("Preparing the audio for playback…");
        setTimeout(loadAudio, 1000);
      } else {
        setNote(st.message, true);
      }
    } catch {
      setNote("The audio could not be loaded. Close and reopen the transcript to try again.", true);
    }
  }
  audio.addEventListener("loadedmetadata", () => {
    audioReady = true;
    for (const b of document.querySelectorAll("#play, #rewind, [data-sample], #sel-play")) b.disabled = false;
  });
  // A failed load is retried once (it can race the copy being made) before it's reported.
  let audioRetried = false;
  audio.addEventListener("error", () => {
    if (!audio.getAttribute("src")) return;
    if (!audioRetried) {
      audioRetried = true;
      audio.removeAttribute("src");
      setTimeout(loadAudio, 1000);
      return;
    }
    setNote("The audio can't be played in this window.", true);
  });

  function applyRate() {
    audio.playbackRate = range && range.slow ? 0.75 : rate;
  }
  function seek(t, keepRange = false) {
    if (!keepRange) range = null;
    applyRate();
    audio.currentTime = Math.min(Math.max(0, t), duration);
    update();
  }
  function playFrom(t) {
    if (!audioReady) return;
    seek(t);
    audio.play();
  }
  function playRange(start, end, opts = {}) {
    if (!audioReady) return;
    range = { start, end, loop: !!opts.loop, slow: !!opts.slow };
    seek(start, true);
    audio.play();
  }
  // Where the cursor was last put in the text. Play starts there if it moved since playback
  // last stopped; otherwise Play resumes.
  let cursorWord = null;
  function togglePlay() {
    if (!audioReady) return;
    if (audio.paused && cursorWord) {
      const at = cursorWord.start;
      cursorWord = null;
      playFrom(at);
      return;
    }
    if (audio.paused) {
      if (range && audio.currentTime >= range.end) audio.currentTime = range.start;
      audio.play();
    } else {
      audio.pause();
    }
  }

  // ---- position: time, timeline, Follow -----------------------------------------------------
  let spokenIndex = -1;
  let playingTurn = -1;
  let lastTypedAt = 0;
  const follow = $("#follow");

  function wordAt(t) {
    let lo = 0;
    let hi = flat.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (flat[mid].start <= t) {
        found = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    // A word stays lit through short pauses after it, not through long silences.
    return found >= 0 && t <= flat[found].end + 1 ? found : -1;
  }

  function inView(node, margin = 40) {
    const r = node.getBoundingClientRect();
    const v = scroller.getBoundingClientRect();
    return r.top >= v.top + margin && r.bottom <= v.bottom - margin;
  }

  function update() {
    const t = audio.currentTime || 0;
    if (range && t >= range.end && !audio.paused) {
      if (range.loop) audio.currentTime = range.start;
      else audio.pause();
    }
    $("#time").textContent = clock(t);
    $("#tl-head").style.left = `${(t / duration) * 100}%`;
    const tl = $("#timeline");
    tl.setAttribute("aria-valuenow", t.toFixed(1));
    tl.setAttribute("aria-valuetext", clock(t));

    const idx = wordAt(t);
    const turn = idx >= 0 ? flat[idx].turn : playingTurn;
    if (turn !== playingTurn) {
      turnsEl.children[playingTurn]?.classList.remove("is-playing");
      turnsEl.children[turn]?.classList.add("is-playing");
      playingTurn = turn;
    }
    const lit = follow.checked ? idx : -1;
    if (lit !== spokenIndex) {
      flat[spokenIndex]?.el?.classList.remove("is-spoken");
      flat[lit]?.el?.classList.add("is-spoken");
      spokenIndex = lit;
      // Follow keeps the playing turn in view, but not while you're typing.
      const typingNow = Date.now() - lastTypedAt < 4000;
      if (lit >= 0 && !audio.paused && !typingNow && flat[lit].el && !inView(flat[lit].el)) keepInView(lit);
    }
  }

  function keepInView(i) {
    const turnEl = turnsEl.children[flat[i].turn];
    if (!turnEl) return;
    const fits = turnEl.offsetHeight < scroller.clientHeight - 120;
    (fits || !flat[i].el ? turnEl : flat[i].el).scrollIntoView({ block: "center", behavior: "smooth" });
  }

  let frame = 0;
  function tick() {
    update();
    frame = audio.paused ? 0 : requestAnimationFrame(tick);
  }
  audio.addEventListener("play", () => {
    cursorWord = null;
    player.classList.add("is-playing");
    $("#play-label").textContent = "Pause";
    $("#play").title = "Pause (Ctrl+Space)";
    if (!frame) frame = requestAnimationFrame(tick);
  });
  audio.addEventListener("pause", () => {
    player.classList.remove("is-playing");
    $("#play-label").textContent = "Play";
    $("#play").title = "Play (Ctrl+Space)";
    update();
  });
  audio.addEventListener("seeked", update);
  follow.addEventListener("change", update);

  // ---- player controls ----------------------------------------------------------------------
  $("#play").addEventListener("click", togglePlay);
  $("#rewind").addEventListener("click", () => seek(audio.currentTime - 5));
  const speeds = [0.75, 1, 1.25, 1.5];
  $("#speed").addEventListener("click", (evt) => {
    rate = speeds[(speeds.indexOf(rate) + 1) % speeds.length];
    evt.currentTarget.textContent = `${rate.toFixed(rate % 0.5 ? 2 : 1)}×`;
    applyRate();
  });

  const timeline = $("#timeline");
  function seekToPointer(evt) {
    const r = timeline.getBoundingClientRect();
    seek(((evt.clientX - r.left) / r.width) * duration);
  }
  timeline.addEventListener("pointerdown", (evt) => {
    if (!audioReady) return;
    timeline.setPointerCapture(evt.pointerId);
    seekToPointer(evt);
  });
  timeline.addEventListener("pointermove", (evt) => {
    if (timeline.hasPointerCapture(evt.pointerId)) seekToPointer(evt);
  });
  timeline.addEventListener("keydown", (evt) => {
    const step = { ArrowLeft: -5, ArrowRight: 5, PageDown: -30, PageUp: 30 }[evt.key];
    if (step !== undefined) seek(audio.currentTime + step);
    else if (evt.key === "Home") seek(0);
    else if (evt.key === "End") seek(duration);
    else return;
    evt.preventDefault();
  });

  $("#speaker-list").addEventListener("click", (evt) => {
    const btn = evt.target.closest("[data-sample]");
    const sample = btn?.closest(".spk-card")._sample;
    if (sample) playRange(sample.start, sample.start + Math.min(5, sample.len));
  });

  // ---- undo and redo ------------------------------------------------------------------------
  const history = { undo: [], redo: [], kind: null, turn: -1, at: 0 };
  const undoBtn = $("#undo");
  const redoBtn = $("#redo");

  function snapshot(caret = caretState()) {
    return {
      speakers: model.speakers.slice(),
      names: { ...model.names },
      turns: model.turns.map((t) => ({ speaker: t.speaker, words: t.words })),
      caret,
    };
  }
  function updateUndo() {
    undoBtn.disabled = !history.undo.length;
    redoBtn.disabled = !history.redo.length;
  }
  // Call before changing the model. Typing in one turn groups into one step until a pause.
  function record(kind, turn = -1) {
    const now = Date.now();
    const grouped = kind === "typing" || kind === "rename";
    const same = grouped && history.kind === kind && history.turn === turn && now - history.at < 1500;
    if (!same) {
      history.undo.push(snapshot());
      if (history.undo.length > 500) history.undo.shift();
    }
    history.redo = [];
    history.kind = kind;
    history.turn = turn;
    history.at = now;
    updateUndo();
  }
  function restore(snap) {
    model.speakers = snap.speakers.slice();
    model.names = { ...snap.names };
    model.turns = snap.turns.map((t) => ({ ...t }));
    renderAll(snap.caret);
    changed();
  }
  function undo() {
    if (!history.undo.length) return;
    hidePopover();
    history.redo.push(snapshot());
    restore(history.undo.pop());
    history.kind = null;
    updateUndo();
  }
  function redo() {
    if (!history.redo.length) return;
    hidePopover();
    history.undo.push(snapshot());
    restore(history.redo.pop());
    history.kind = null;
    updateUndo();
  }
  undoBtn.addEventListener("click", undo);
  redoBtn.addEventListener("click", redo);

  // ---- saving -------------------------------------------------------------------------------
  const saveState = $("#save-state");
  let saveTimer = 0;
  let saving = false;
  let pending = false;
  let savedAt = null;
  let saveError = null;

  function showSaveState() {
    let text = "";
    if (saveError) text = `Not saved: ${saveError}`;
    else if (saving || pending) text = "Saving…";
    else if (savedAt) {
      const mins = Math.floor((Date.now() - savedAt) / 60000);
      text = mins < 1 ? "Saved" : `Saved ${mins} min ago`;
    }
    saveState.textContent = text ? ` · ${text}` : "";
    saveState.classList.toggle("is-error", !!saveError);
  }
  setInterval(showSaveState, 30000);

  function payload() {
    return {
      speakers: model.speakers,
      names: model.names,
      turns: model.turns
        .filter((t) => t.words.length)
        .map((t) => ({
          speaker: t.speaker,
          words: t.words.map((w) => ({ word: w.text, start: w.start, end: w.end })),
        })),
    };
  }
  async function save() {
    clearTimeout(saveTimer);
    if (saving || !pending) return;
    saving = true;
    pending = false;
    showSaveState();
    let retry = 0;
    try {
      const resp = await fetch(`/jobs/${data.job}/revision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      if (resp.status === 422) {
        const body = await resp.json().catch(() => ({}));
        saveError = `the edit was refused (${body.error || "invalid"}). Undo the last change, then edit again.`;
      } else if (!resp.ok) {
        throw new Error(resp.statusText);
      } else {
        savedAt = Date.now();
        saveError = null;
      }
    } catch {
      saveError = "the app isn't answering; trying again.";
      pending = true;
      retry = 5000;
    } finally {
      saving = false;
      showSaveState();
      if (pending) saveTimer = setTimeout(save, retry || 300);
    }
  }
  function changed({ speakers = true } = {}) {
    pending = true;
    showSaveState();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 1000);
    if (speakers) renderSpeakers();
    renderTimeline();
  }
  async function flushSaves() {
    const until = Date.now() + 5000;
    while ((pending || saving) && Date.now() < until) {
      if (!saving) await save();
      else await new Promise((r) => setTimeout(r, 50));
    }
  }
  // Leaving through a link waits for the last save; closing the window asks first.
  document.addEventListener(
    "click",
    async (evt) => {
      const a = evt.target.closest("a[href]");
      if (!a || !(pending || saving)) return;
      evt.preventDefault();
      evt.stopPropagation();
      await flushSaves();
      window.location.href = a.href;
    },
    true,
  );
  window.addEventListener("beforeunload", (evt) => {
    if (pending || saving) evt.preventDefault();
  });
  // A reload or a closing window doesn't wait for fetch(); a beacon is delivered anyway.
  window.addEventListener("pagehide", () => {
    if (!pending && !saving) return;
    // text/plain: a beacon may not carry a JSON content type; the server parses it anyway.
    const body = new Blob([JSON.stringify(payload())], { type: "text/plain" });
    if (navigator.sendBeacon(`/jobs/${data.job}/revision`, body)) pending = false;
  });

  // ---- typing -------------------------------------------------------------------------------
  let idleTimer = 0;

  function syncText(p) {
    const ti = turnIndex(p);
    const turn = model.turns[ti];
    if (!editBase.has(ti)) editBase.set(ti, turn.words);
    const [t0, t1] = window_(ti);
    turn.words = retime(splitWords(p.innerText), editBase.get(ti), t0, t1);
    dirty.add(ti);
    lastTypedAt = Date.now();
  }
  // Rebuild the word elements of edited turns once typing pauses, keeping the caret.
  function flushDirty(force = false) {
    if (!dirty.size) return;
    const caret = caretState();
    const sel = window.getSelection();
    for (const ti of [...dirty]) {
      const p = textOf(ti);
      if (!p) { dirty.delete(ti); continue; }
      const here = p.contains(sel.focusNode);
      // Don't swallow a space just typed at the caret, or an open selection.
      if (here && !force && (!caret || caret.space)) continue;
      fillText(p, model.turns[ti]);
      dirty.delete(ti);
      editBase.delete(ti);
      if (here && caret) placeCaret(p, caret.ns, caret.space);
    }
    reindex();
  }
  // A turn left empty is removed when the caret leaves it.
  function dropEmpty(ti) {
    if (model.turns[ti] && !model.turns[ti].words.length) {
      model.turns.splice(ti, 1);
      turnsEl.children[ti].remove();
      dirty.delete(ti);
      // Indexes after the removed turn shift down by one.
      const shift = (m) => new Map([...m].map(([k, v]) => [k > ti ? k - 1 : k, v]));
      const d = [...dirty].map((k) => (k > ti ? k - 1 : k));
      dirty.clear();
      d.forEach((k) => dirty.add(k));
      const b = shift(editBase);
      editBase.clear();
      b.forEach((v, k) => editBase.set(k, v));
      reindex();
      changed();
    }
  }

  turnsEl.addEventListener("beforeinput", (evt) => {
    const p = evt.target.closest?.(".turn-text");
    if (!p) return;
    if (evt.inputType === "historyUndo" || evt.inputType === "historyRedo") {
      evt.preventDefault();
      if (evt.inputType === "historyUndo") undo();
      else redo();
      return;
    }
    if (evt.inputType === "insertParagraph" || evt.inputType === "insertLineBreak") {
      evt.preventDefault(); // Enter splits the turn (keydown)
      return;
    }
    record("typing", turnIndex(p));
  });
  turnsEl.addEventListener("input", (evt) => {
    const p = evt.target.closest?.(".turn-text");
    if (!p || evt.isComposing) return;
    syncText(p);
    changed();
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => flushDirty(), 1000);
  });
  turnsEl.addEventListener("compositionend", (evt) => {
    const p = evt.target.closest?.(".turn-text");
    if (!p) return;
    syncText(p);
    changed();
  });
  turnsEl.addEventListener("focusout", (evt) => {
    const p = evt.target.closest?.(".turn-text");
    if (!p) return;
    const ti = turnIndex(p);
    if (dirty.has(ti)) {
      fillText(p, model.turns[ti]);
      dirty.delete(ti);
      editBase.delete(ti);
      reindex();
    }
    dropEmpty(ti);
  });

  // ---- splitting, joining, speakers ---------------------------------------------------------
  // A turn cut in two at the cursor: the words before it and from it, timed.
  function cutAtCaret(p) {
    const sel = window.getSelection();
    if (!sel.rangeCount || !p.contains(sel.anchorNode)) return null;
    const ti = turnIndex(p);
    const turn = model.turns[ti];
    const r = sel.getRangeAt(0);
    const head = document.createRange();
    head.selectNodeContents(p);
    head.setEnd(r.startContainer, r.startOffset);
    const tail = document.createRange();
    tail.selectNodeContents(p);
    tail.setStart(r.endContainer, r.endOffset);
    const a = splitWords(head.toString());
    const b = splitWords(tail.toString());
    const [t0, t1] = window_(ti);
    const timed = retime(a.concat(b), editBase.get(ti) || turn.words, t0, t1);
    return { ti, speaker: turn.speaker, head: timed.slice(0, a.length), tail: timed.slice(a.length) };
  }
  const nsOf = (words) => words.reduce((n, w) => n + nonSpace(w.text), 0);

  function splitTurn(p) {
    const cut = cutAtCaret(p);
    if (!cut || !cut.head.length || !cut.tail.length) return; // nothing to split off at an end
    record("split");
    model.turns.splice(cut.ti, 1,
      { speaker: cut.speaker, words: cut.head },
      { speaker: cut.speaker, words: cut.tail });
    renderAll({ turn: cut.ti + 1, ns: 0, space: false });
    changed();
  }

  // Move the text from the cursor to the end into the next turn (or, at the last turn, into
  // a new turn whose speaker is chosen), or the text up to the cursor into the previous one.
  function moveText(p, direction) {
    const cut = cutAtCaret(p);
    if (!cut) return;
    const { ti, speaker, head, tail } = cut;
    const moving = direction === "next" ? tail : head;
    const staying = direction === "next" ? head : tail;
    if (!moving.length) return;
    const near = direction === "next" ? ti + 1 : ti - 1;
    const apply = (newSpeaker) => {
      record("move");
      if (newSpeaker && !model.speakers.includes(newSpeaker)) model.speakers.push(newSpeaker);
      const turns = model.turns.slice();
      turns[ti] = { speaker, words: staying };
      let caret;
      if (!newSpeaker) {
        const other = turns[near];
        const words = direction === "next" ? moving.concat(other.words) : other.words.concat(moving);
        turns[near] = { speaker: other.speaker, words };
        caret = { turn: near, ns: direction === "next" ? 0 : nsOf(other.words) };
      } else {
        turns.splice(direction === "next" ? ti + 1 : ti, 0, { speaker: newSpeaker, words: moving });
        caret = { turn: direction === "next" ? ti + 1 : ti, ns: 0 };
      }
      const gone = !staying.length && caret.turn > ti ? 1 : 0; // the cut turn emptied out
      model.turns = turns.filter((t) => t.words.length);
      renderAll({ turn: caret.turn - gone, ns: caret.ns, space: false });
      changed();
    };
    if (near >= 0 && near < model.turns.length) apply(null);
    else {
      openMenu(turnsEl.children[ti].querySelector(".turn-speaker"), {
        speakers: model.speakers.filter((sp) => sp !== speaker),
        fresh: true,
        onPick: (id) => apply(id || newSpeakerId()),
      });
    }
  }

  function joinTurns(ti) {
    // Joins turn ti + 1 onto turn ti; the joined turn keeps the first one's speaker.
    const first = model.turns[ti];
    const second = model.turns[ti + 1];
    if (!first || !second) return;
    record("join");
    const ns = first.words.reduce((n, w) => n + nonSpace(w.text), 0);
    model.turns.splice(ti, 2, { speaker: first.speaker, words: first.words.concat(second.words) });
    renderAll({ turn: ti, ns, space: false });
    changed();
  }

  function newSpeakerId() {
    for (let n = 0; ; n++) {
      const id = `SPEAKER_${pad(n)}`;
      if (!model.speakers.includes(id)) return id;
    }
  }
  function setSpeaker(ti, id) {
    const turn = model.turns[ti];
    if (!turn || turn.speaker === id) return;
    const caret = caretState();
    record("speaker");
    if (!model.speakers.includes(id)) model.speakers.push(id);
    model.turns[ti] = { speaker: id, words: turn.words };
    renderAll(caret);
    changed();
  }

  // ---- the speakers panel: names and merging --------------------------------------------
  function renameSpeaker(id, value) {
    record("rename", model.speakers.indexOf(id));
    const names = { ...model.names };
    if (value.trim()) names[id] = value;
    else delete names[id];
    model.names = names;
    // Relabel in place, so the name box keeps focus while you type.
    model.turns.forEach((turn, ti) => {
      if (turn.speaker !== id) return;
      const label = turnsEl.children[ti]?.querySelector(".turn-speaker span");
      if (label) label.textContent = speakerName(id);
    });
    changed({ speakers: false });
  }
  function mergeSpeakers(from, into) {
    if (from === into) return;
    record("merge-speaker");
    model.turns = model.turns.map((t) => (t.speaker === from ? { speaker: into, words: t.words } : t));
    model.speakers = model.speakers.filter((sp) => sp !== from);
    const names = { ...model.names };
    delete names[from];
    model.names = names;
    renderAll();
    changed();
    $(`#speaker-list .spk-card [data-merge="${CSS.escape(into)}"]`)?.closest(".spk-card")?.querySelector(".spk-input")?.focus();
  }
  const speakerList = $("#speaker-list");
  speakerList.addEventListener("input", (evt) => {
    const box = evt.target.closest(".spk-input");
    if (box) renameSpeaker(box.dataset.speaker, box.value);
  });
  speakerList.addEventListener("keydown", (evt) => {
    if (evt.target.closest(".spk-input") && evt.key === "Enter") evt.target.blur();
  });
  speakerList.addEventListener("click", (evt) => {
    const btn = evt.target.closest(".spk-merge");
    if (!btn) return;
    const from = btn.dataset.merge;
    const used = new Set(model.turns.filter((t) => t.words.length).map((t) => t.speaker));
    if (!menu.hidden && menuBack === btn) {
      closeMenu();
      return;
    }
    openMenu(btn, {
      speakers: model.speakers.filter((sp) => sp !== from && used.has(sp)),
      onPick: (into) => mergeSpeakers(from, into),
    });
  });

  // One floating menu of speakers, used by a turn's speaker button and by "Merge into…".
  let menuPick = null;
  let menuBack = null;
  function openMenu(anchor, { speakers, current = null, fresh = false, onPick }) {
    const items = speakers.map((sp) => {
      const b = el("button", "menu-item");
      b.type = "button";
      b.setAttribute("role", current === null ? "menuitem" : "menuitemradio");
      if (current !== null) b.setAttribute("aria-checked", String(sp === current));
      b.dataset.speaker = sp;
      b.style.setProperty("--spk", speakerColour(sp));
      b.append(el("span", "menu-dot"), el("span", "", speakerName(sp)));
      return b;
    });
    const extra = [];
    if (fresh) {
      const b = el("button", "menu-item", "New speaker");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.dataset.speaker = "";
      extra.push(el("hr"), b);
    }
    menu.replaceChildren(...items, ...extra);
    menuPick = onPick;
    menuBack = anchor;
    menu.hidden = false;
    const r = anchor.getBoundingClientRect();
    const top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8);
    menu.style.top = `${Math.round(top)}px`;
    menu.style.left = `${Math.round(Math.min(r.left, window.innerWidth - menu.offsetWidth - 8))}px`;
    (menu.querySelector('[aria-checked="true"]') || menu.querySelector(".menu-item")).focus();
  }
  function closeMenu(refocus = true) {
    if (menu.hidden) return;
    menu.hidden = true;
    if (refocus && menuBack?.isConnected) menuBack.focus();
  }
  function openTurnMenu(btn) {
    const ti = turnIndex(btn);
    openMenu(btn, {
      speakers: model.speakers,
      current: model.turns[ti].speaker,
      fresh: true,
      onPick: (id) => {
        setSpeaker(ti, id || newSpeakerId());
        turnsEl.children[ti]?.querySelector(".turn-speaker")?.focus();
      },
    });
  }
  menu.addEventListener("click", (evt) => {
    const item = evt.target.closest(".menu-item");
    if (!item) return;
    const pick = menuPick;
    closeMenu(false);
    pick(item.dataset.speaker);
  });
  menu.addEventListener("keydown", (evt) => {
    const items = [...menu.querySelectorAll(".menu-item")];
    const i = items.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowUp: -1 }[evt.key];
    if (step) {
      evt.preventDefault();
      items[(i + step + items.length) % items.length].focus();
    } else if (evt.key === "Tab") {
      closeMenu();
    }
  });
  document.addEventListener("pointerdown", (evt) => {
    if (!menu.hidden && !menu.contains(evt.target) && !evt.target.closest(".turn-speaker, .spk-merge")) closeMenu(false);
  });

  // ---- the right-click menu in the text -----------------------------------------------------
  const ctx = $("#ctx-menu");
  function closeCtx() {
    ctx.hidden = true;
  }
  function ctxItem(label, key, action, disabled = false) {
    const b = el("button", "menu-item");
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.append(el("span", "", label));
    if (key) b.append(el("span", "menu-key", key));
    b.disabled = disabled;
    b._action = action;
    return b;
  }
  turnsEl.addEventListener("contextmenu", (evt) => {
    const p = evt.target.closest(".turn-text");
    if (!p) return;
    evt.preventDefault();
    closeMenu(false);
    const live = window.getSelection();
    const inText = live.rangeCount && !live.isCollapsed && turnsEl.contains(live.anchorNode);
    let items;
    if (virtual || inText) {
      if (!selection) showPopover();
      const s = selection;
      const text = s ? s.picked.map((w) => w.text).join(" ") : live.toString();
      items = [
        ctxItem("Play selection", "Space", playSelection, !audioReady || !s),
        ctxItem("Copy", "Ctrl+C", () => navigator.clipboard?.writeText(text)),
        ...(s && s.to > s.from ? [ctxItem(`Merge ${s.to - s.from + 1} turns into one`, "", mergeSelection)] : []),
        againItem(s),
      ];
    } else {
      // Put the cursor where the click was (keyboard menus keep the cursor where it is).
      // A right-clicked word counts from its start: "from here" means from this word.
      const pos = evt.clientX || evt.clientY ? pointPos(evt.clientX, evt.clientY) : null;
      if (pos) {
        const words = model.turns[pos.turn].words;
        const wi = words.length ? wordAtNs(model.turns[pos.turn], pos.ns) : 0;
        placeCaret(textOf(pos.turn), nsOf(words.slice(0, wi)));
      }
      const here = textOf(pos ? pos.turn : turnIndex(p));
      const ti = turnIndex(here);
      items = [
        ctxItem("Play from here", "Ctrl+click", () => {
          const c = caretState();
          const turn = model.turns[ti];
          if (c && turn.words.length) playFrom(turn.words[wordAtNs(turn, c.ns)].start);
        }, !audioReady),
        ctxItem("Split turn here", "Enter", () => splitTurn(here)),
        ctxItem("Move rest to next turn", "Alt+Shift+↓", () => moveText(here, "next")),
        ctxItem("Move start to previous turn", "Alt+Shift+↑", () => moveText(here, "previous")),
      ];
    }
    ctx.replaceChildren(...items);
    ctx.hidden = false;
    let x = evt.clientX;
    let y = evt.clientY;
    if (!x && !y) {
      const c = window.getSelection().rangeCount ? window.getSelection().getRangeAt(0).getBoundingClientRect() : p.getBoundingClientRect();
      [x, y] = [c.left, c.bottom];
    }
    ctx.style.left = `${Math.round(Math.min(x, window.innerWidth - ctx.offsetWidth - 8))}px`;
    ctx.style.top = `${Math.round(Math.min(y, window.innerHeight - ctx.offsetHeight - 8))}px`;
    ctx.querySelector(".menu-item:not(:disabled)")?.focus();
  });
  ctx.addEventListener("click", (evt) => {
    const item = evt.target.closest(".menu-item");
    if (!item || item.disabled) return;
    closeCtx();
    item._action();
  });
  ctx.addEventListener("keydown", (evt) => {
    const items = [...ctx.querySelectorAll(".menu-item:not(:disabled)")];
    const i = items.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowUp: -1 }[evt.key];
    if (step) {
      evt.preventDefault();
      items[(i + step + items.length) % items.length].focus();
    } else if (evt.key === "Tab") closeCtx();
  });
  document.addEventListener("pointerdown", (evt) => {
    if (!ctx.hidden && !ctx.contains(evt.target)) closeCtx();
  });

  // ---- clicks and keys in the transcript ----------------------------------------------------
  turnsEl.addEventListener("click", (evt) => {
    const time = evt.target.closest(".turn-time");
    if (time) {
      const turn = model.turns[turnIndex(time)];
      if (turn.words.length) playFrom(turnStart(turn));
      return;
    }
    const who = evt.target.closest(".turn-speaker");
    if (who) {
      if (!menu.hidden && menuBack === who) closeMenu();
      else openTurnMenu(who);
      return;
    }
    const p = evt.target.closest(".turn-text");
    if (p && (evt.ctrlKey || evt.metaKey)) {
      const c = caretState();
      const turn = model.turns[turnIndex(p)];
      if (c && turn.words.length) playFrom(turn.words[wordAtNs(turn, c.ns)].start);
    }
  });
  const ctrlClass = (on) => turnsEl.classList.toggle("ctrl-down", on);
  document.addEventListener("keydown", (evt) => ctrlClass(evt.ctrlKey || evt.metaKey));
  document.addEventListener("keyup", (evt) => ctrlClass(evt.ctrlKey || evt.metaKey));
  window.addEventListener("blur", () => ctrlClass(false));

  turnsEl.addEventListener("keydown", (evt) => {
    const p = evt.target.closest?.(".turn-text");
    const ti = p ? turnIndex(p) : evt.target.closest?.(".turn-speaker") ? turnIndex(evt.target) : -1;
    if (ti < 0) return;
    if (virtual && !["Shift", "Control", "Alt", "Meta", " ", "Escape"].includes(evt.key)) {
      hidePopover(false); // typing ends a selection across turns
    }
    if (evt.altKey && evt.shiftKey && p && (evt.key === "ArrowUp" || evt.key === "ArrowDown")) {
      evt.preventDefault();
      moveText(p, evt.key === "ArrowDown" ? "next" : "previous");
      return;
    }
    if (evt.altKey && (evt.key === "ArrowUp" || evt.key === "ArrowDown")) {
      evt.preventDefault();
      const list = model.speakers;
      const at = list.indexOf(model.turns[ti].speaker);
      setSpeaker(ti, list[(at + (evt.key === "ArrowUp" ? -1 : 1) + list.length) % list.length]);
      return;
    }
    if (!p || evt.ctrlKey || evt.metaKey || evt.altKey) return;
    const sel = window.getSelection();
    if (evt.key === "Enter") {
      evt.preventDefault();
      if (!evt.shiftKey) splitTurn(p);
    } else if ((evt.key === "Backspace" || evt.key === "Delete") && sel.isCollapsed) {
      const r = document.createRange();
      r.selectNodeContents(p);
      if (evt.key === "Backspace") r.setEnd(sel.focusNode, sel.focusOffset);
      else r.setStart(sel.focusNode, sel.focusOffset);
      if (r.toString().trim()) return;
      if (evt.key === "Backspace" && ti > 0) {
        evt.preventDefault();
        joinTurns(ti - 1);
      } else if (evt.key === "Delete" && ti < model.turns.length - 1) {
        evt.preventDefault();
        joinTurns(ti);
      }
    }
  });

  // ---- select and listen, replace, merge turns ----------------------------------------------
  // A selection, as words: {from, to (turn indexes), first, last (word indexes), start, end}.
  let selection = null;

  function selectedWords() {
    const sel = window.getSelection();
    if (!sel.rangeCount || sel.isCollapsed) return null;
    const r = sel.getRangeAt(0);
    if (!turnsEl.contains(r.commonAncestorContainer)) return null;
    const node = (n) => (n.nodeType === 1 ? n : n.parentElement);
    const startTurn = node(r.startContainer).closest(".turn");
    const endTurn = node(r.endContainer).closest(".turn");
    let from = startTurn ? turnIndex(startTurn) : 0;
    let to = endTurn ? turnIndex(endTurn) : model.turns.length - 1;
    // Where the selection starts and ends inside each turn's text, in non-space characters.
    const startText = node(r.startContainer).closest(".turn-text");
    const endText = node(r.endContainer).closest(".turn-text");
    let s = startText ? nsBefore(startText, r.startContainer, r.startOffset) : 0;
    let e = endText ? nsBefore(endText, r.endContainer, r.endOffset) : Infinity;
    if (!endText && endTurn && r.endContainer !== endTurn && to > from) {
      to -= 1; // it ends in the next turn's header, before any of its words
      e = Infinity;
    }
    return wordsBetween(from, s, to, e, r.getBoundingClientRect());
  }

  // The words from non-space offset `s` in turn `from` to offset `e` in turn `to`.
  function wordsBetween(from, s, to, e, rect) {
    // Skip turns the selection only touches at their very end.
    const words = (ti) => model.turns[ti].words;
    const firstIn = (ti, ns) => {
      let cum = 0;
      for (let i = 0; i < words(ti).length; i++) {
        cum += nonSpace(words(ti)[i].text);
        if (cum > ns) return i;
      }
      return -1;
    };
    let first = firstIn(from, s);
    while (first < 0 && from < to) {
      from += 1;
      s = 0;
      first = firstIn(from, 0);
    }
    if (first < 0) return null;
    const lastIn = (ti, ns) => {
      if (ns === Infinity) return words(ti).length - 1;
      let cum = 0;
      let last = -1;
      for (let i = 0; i < words(ti).length; i++) {
        if (cum < ns) last = i;
        cum += nonSpace(words(ti)[i].text);
      }
      return last;
    };
    let last = lastIn(to, e);
    while (last < 0 && to > from) {
      to -= 1;
      last = words(to).length - 1;
    }
    if (last < 0 || (from === to && last < first)) return null;
    let count = 0;
    for (let ti = from; ti <= to; ti++) {
      const a = ti === from ? first : 0;
      const b = ti === to ? last : words(ti).length - 1;
      count += b - a + 1;
    }
    const picked = [];
    for (let ti = from; ti <= to; ti++) {
      const a = ti === from ? first : 0;
      const b = ti === to ? last : words(ti).length - 1;
      picked.push(...words(ti).slice(a, b + 1));
    }
    return {
      from, to, first, last, count, picked,
      start: words(from)[first].start,
      end: words(to)[last].end,
      rect,
    };
  }

  // Shift+click in another turn: turns are separate editable boxes, and browsers won't drag a
  // selection across them, so the editor makes one itself, from where the last selection or
  // cursor started to the click, and paints it with a CSS highlight.
  let anchorPos = null; // {turn, ns} where the last selection in the text started
  let virtual = null; // {from, s, to, e} while a selection across turns is shown
  const crossHl = window.CSS && CSS.highlights && window.Highlight ? new Highlight() : null;
  if (crossHl) CSS.highlights.set("wm-selection", crossHl);

  function pointPos(x, y) {
    let node;
    let offset;
    if (document.caretPositionFromPoint) {
      const c = document.caretPositionFromPoint(x, y);
      if (!c) return null;
      [node, offset] = [c.offsetNode, c.offset];
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (!r) return null;
      [node, offset] = [r.startContainer, r.startOffset];
    } else return null;
    const p = (node.nodeType === 1 ? node : node.parentElement)?.closest(".turn-text");
    if (!p || !turnsEl.contains(p)) return null;
    return { turn: turnIndex(p), ns: nsBefore(p, node, offset), node, offset };
  }
  // The DOM position after `ns` non-space characters of `p` (Infinity: the end).
  function nsPoint(p, ns) {
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let count = 0;
    let node;
    let last = null;
    while ((node = walker.nextNode())) {
      last = node;
      for (let i = 0; i < node.data.length; i++) {
        if (count === ns && !/\s/.test(node.data[i])) return { node, offset: i };
        if (!/\s/.test(node.data[i])) count++;
      }
    }
    return last ? { node: last, offset: last.data.length } : { node: p, offset: p.childNodes.length };
  }
  function paintVirtual() {
    if (!crossHl) return;
    crossHl.clear();
    if (!virtual) return;
    for (let ti = virtual.from; ti <= virtual.to; ti++) {
      const p = textOf(ti);
      if (!p) continue;
      const a = nsPoint(p, ti === virtual.from ? virtual.s : 0);
      const b = nsPoint(p, ti === virtual.to ? virtual.e : Infinity);
      const r = document.createRange();
      r.setStart(a.node, a.offset);
      r.setEnd(b.node, b.offset);
      crossHl.add(r);
    }
  }
  function clearVirtual() {
    virtual = null;
    crossHl?.clear();
  }
  turnsEl.addEventListener("mousedown", (evt) => {
    if (evt.button !== 0) return;
    if (!evt.shiftKey) {
      if (virtual) hidePopover(false);
      return;
    }
    const here = pointPos(evt.clientX, evt.clientY);
    if (!here || !anchorPos || here.turn === anchorPos.turn) {
      clearVirtual(); // within one turn the browser's own Shift+click works
      return;
    }
    evt.preventDefault();
    const [a, b] = here.turn > anchorPos.turn ? [anchorPos, here] : [here, anchorPos];
    virtual = { from: a.turn, s: a.ns, to: b.turn, e: b.ns };
    paintVirtual();
    showPopover({ left: evt.clientX, right: evt.clientX, top: evt.clientY - 10, bottom: evt.clientY + 10 });
    dismissTip(); // learnt
  });

  // The tip, shown on the first selection until dismissed (or Shift+click is used).
  const tip = $("#sel-tip");
  let tipDismissed = (data.tips_dismissed || []).includes("shift-select");
  function dismissTip() {
    tip.hidden = true;
    if (tipDismissed) return;
    tipDismissed = true;
    fetch("/settings/ui", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dismiss_tip: "shift-select" }),
    }).catch(() => {});
  }
  $("#sel-tip-close").addEventListener("click", dismissTip);

  const replaceInput = $("#sel-replace");
  const mergeRow = $("#sel-merge");
  const mergeSpeaker = $("#sel-merge-speaker");

  function showPopover(at = null) {
    selection = virtual
      ? wordsBetween(virtual.from, virtual.s, virtual.to, virtual.e, at || selection?.rect)
      : selectedWords();
    if (selection && !virtual && !tipDismissed) tip.hidden = false;
    const band = $("#tl-sel");
    if (!selection) {
      hidePopover(false);
      return;
    }
    const { count, from, to } = selection;
    $("#sel-count").textContent = `${count} word${count === 1 ? "" : "s"} selected`;
    $("#sel-range").textContent = `${clock(selection.start, true)} – ${clock(selection.end, true)}`;
    replaceInput.value = selection.picked.map((w) => w.text).join(" ");
    mergeRow.hidden = to === from;
    if (to > from) {
      $("#sel-merge-label").textContent = `Merge ${to - from + 1} turns into one, said by`;
      mergeSpeaker.replaceChildren(
        ...model.speakers.map((s) => {
          const o = el("option", "", speakerName(s));
          o.value = s;
          o.selected = s === model.turns[from].speaker;
          return o;
        }),
      );
    }
    band.hidden = false;
    band.style.left = `${(selection.start / duration) * 100}%`;
    band.style.width = `max(2px, ${((selection.end - selection.start) / duration) * 100}%)`;
    pop.hidden = false;
    const r = selection.rect;
    const h = pop.offsetHeight;
    const top0 = scroller.getBoundingClientRect().top;
    let top = r.top - h - 10;
    if (top < top0 + 8) top = Math.min(r.bottom + 10, window.innerHeight - h - 8);
    pop.style.top = `${Math.round(top)}px`;
    pop.style.left = `${Math.round(Math.min(Math.max(r.left, 16), window.innerWidth - pop.offsetWidth - 16))}px`;
  }

  function hidePopover(clearSelection = true) {
    clearVirtual();
    if (pop.hidden && !selection) return;
    const refocus = pop.contains(document.activeElement);
    pop.hidden = true;
    selection = null;
    $("#tl-sel").hidden = true;
    if (clearSelection) {
      const sel = window.getSelection();
      if (sel.rangeCount && !sel.isCollapsed) sel.collapseToEnd();
    }
    if (refocus) document.activeElement.blur();
  }

  let selTimer = 0;
  document.addEventListener("selectionchange", () => {
    if (virtual) return; // a selection across turns is the editor's own
    const live = window.getSelection();
    if (live.rangeCount && turnsEl.contains(live.anchorNode)) {
      const p = (live.anchorNode.nodeType === 1 ? live.anchorNode : live.anchorNode.parentElement).closest(".turn-text");
      if (p) anchorPos = { turn: turnIndex(p), ns: nsBefore(p, live.anchorNode, live.anchorOffset) };
    }
    const c = caretState();
    if (c && audio.paused) {
      const turn = model.turns[c.turn];
      if (turn && turn.words.length) cursorWord = turn.words[wordAtNs(turn, c.ns)];
    }
    clearTimeout(selTimer);
    selTimer = setTimeout(() => {
      if (pop.contains(document.activeElement)) return; // using the popover keeps it open
      showPopover();
    }, 120);
  });
  // Scrolling hides the popover (it would float off its words) but keeps the selection.
  scroller.addEventListener("scroll", () => {
    if (!pop.hidden && !pop.contains(document.activeElement)) {
      pop.hidden = true;
      $("#tl-sel").hidden = true;
    }
  });

  const loop = $("#sel-loop");
  const slow = $("#sel-slow");
  function toggle(btn) {
    const on = btn.getAttribute("aria-pressed") !== "true";
    btn.setAttribute("aria-pressed", String(on));
    if (range) {
      range.loop = loop.getAttribute("aria-pressed") === "true";
      range.slow = slow.getAttribute("aria-pressed") === "true";
      applyRate();
    }
  }
  loop.addEventListener("click", () => toggle(loop));
  slow.addEventListener("click", () => toggle(slow));
  function playSelection() {
    if (!selection) return;
    if (range && range.start === selection.start && !audio.paused) {
      audio.pause();
      return;
    }
    playRange(selection.start, selection.end, {
      loop: loop.getAttribute("aria-pressed") === "true",
      slow: slow.getAttribute("aria-pressed") === "true",
    });
  }
  $("#sel-play").addEventListener("click", playSelection);

  // Replace the selected words. Across turns, the new words go where the selection starts,
  // the rest of the last turn stays a turn of its own, and turns in between go.
  function replaceSelection(text) {
    const s = selection;
    if (!s) return;
    clearVirtual();
    flushDirty(true);
    record("replace");
    const fresh = retime(splitWords(text), s.picked, s.start, s.end);
    const head = model.turns[s.from];
    const tail = model.turns[s.to];
    const before = head.words.slice(0, s.first);
    const updated = [{ speaker: head.speaker, words: before.concat(fresh, s.from === s.to ? head.words.slice(s.last + 1) : []) }];
    if (s.to > s.from) updated.push({ speaker: tail.speaker, words: tail.words.slice(s.last + 1) });
    model.turns.splice(s.from, s.to - s.from + 1, ...updated.filter((t) => t.words.length));
    const ns = before.concat(fresh).reduce((n, w) => n + nonSpace(w.text), 0);
    hidePopover(false);
    const at = Math.min(s.from, model.turns.length - 1);
    renderAll(at >= 0 ? { turn: at, ns, space: false } : null);
    changed();
  }
  $("#sel-replace-btn").addEventListener("click", () => replaceSelection(replaceInput.value));
  replaceInput.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") {
      evt.preventDefault();
      replaceSelection(replaceInput.value);
    }
  });
  $("#sel-cancel").addEventListener("click", () => hidePopover());

  function mergeSelection() {
    const s = selection;
    if (!s || s.to === s.from) return;
    clearVirtual();
    flushDirty(true);
    record("merge");
    const words = model.turns.slice(s.from, s.to + 1).flatMap((t) => t.words);
    model.turns.splice(s.from, s.to - s.from + 1, { speaker: mergeSpeaker.value, words });
    hidePopover(false);
    renderAll({ turn: s.from, ns: 0, space: false });
    changed();
  }
  $("#sel-merge-btn").addEventListener("click", mergeSelection);


  // ---- find and replace ---------------------------------------------------------------------
  // Matches are found in each turn's text (its words joined by single spaces, which is what
  // a rendered turn shows) and painted with the CSS Custom Highlight API, so the editable
  // text is never touched. Without that API, the current match is selected instead.
  const findInput = $("#find");
  const replInput = $("#find-replace");
  const findCount = $("#find-count");
  const replaceRow = $("#replace-row");
  const findToggle = $("#find-toggle");
  const hl = window.CSS && CSS.highlights && window.Highlight ? { all: new Highlight(), cur: new Highlight() } : null;
  if (hl) {
    CSS.highlights.set("wm-find", hl.all);
    CSS.highlights.set("wm-find-current", hl.cur);
  }
  let matches = [];
  let current = -1;
  const joined = (turn) => turn.words.map((w) => w.text).join(" ");

  function search() {
    const q = findInput.value.toLowerCase();
    matches = [];
    if (q) {
      model.turns.forEach((turn, ti) => {
        const text = joined(turn).toLowerCase();
        for (let i = text.indexOf(q); i >= 0; i = text.indexOf(q, i + q.length)) {
          matches.push({ turn: ti, start: i, end: i + q.length });
        }
      });
    }
    current = matches.length ? Math.min(Math.max(current, 0), matches.length - 1) : -1;
    paint();
  }

  function domRange(m) {
    if (dirty.has(m.turn)) return null; // its elements are being typed in
    const p = textOf(m.turn);
    if (!p) return null;
    const r = document.createRange();
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let at = 0;
    let node;
    let started = false;
    while ((node = walker.nextNode())) {
      const len = node.data.length;
      if (!started && m.start <= at + len) {
        r.setStart(node, m.start - at);
        started = true;
      }
      if (started && m.end <= at + len) {
        r.setEnd(node, m.end - at);
        return r;
      }
      at += len;
    }
    return null;
  }

  function paint() {
    findCount.textContent = findInput.value
      ? matches.length ? `${current + 1} of ${matches.length}` : "No matches"
      : "";
    if (!hl) return;
    hl.all.clear();
    hl.cur.clear();
    matches.forEach((m, i) => {
      const r = domRange(m);
      if (r) (i === current ? hl.cur : hl.all).add(r);
    });
  }

  function go(step) {
    if (!matches.length) return;
    current = (current + step + matches.length) % matches.length;
    paint();
    const r = domRange(matches[current]);
    if (!r) return;
    const box = r.getBoundingClientRect();
    const v = scroller.getBoundingClientRect();
    if (box.top < v.top + 80 || box.bottom > v.bottom - 40) {
      scroller.scrollBy({ top: box.top - v.top - v.height / 2, behavior: "smooth" });
    }
    if (!hl) {
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    }
  }

  // Replace character ranges of one turn's text, re-timing the words that changed.
  function replaceInTurn(ti, ranges, text) {
    const turn = model.turns[ti];
    let s = joined(turn);
    for (const m of [...ranges].sort((a, b) => b.start - a.start)) s = s.slice(0, m.start) + text + s.slice(m.end);
    const [t0, t1] = window_(ti);
    model.turns[ti] = { speaker: turn.speaker, words: retime(splitWords(s), turn.words, t0, t1) };
  }
  function afterReplace() {
    model.turns = model.turns.filter((t) => t.words.length);
    renderAll(null);
    changed();
    search();
  }
  function replaceOne() {
    if (current < 0) return;
    flushDirty(true);
    record("replace");
    const m = matches[current];
    replaceInTurn(m.turn, [m], replInput.value);
    afterReplace();
    if (matches.length) go(0);
  }
  function replaceAll() {
    if (!matches.length) return;
    flushDirty(true);
    record("replace-all");
    const n = matches.length;
    const byTurn = new Map();
    for (const m of matches) byTurn.set(m.turn, [...(byTurn.get(m.turn) || []), m]);
    byTurn.forEach((ranges, ti) => replaceInTurn(ti, ranges, replInput.value));
    afterReplace();
    findCount.textContent = `Replaced ${n}`;
  }

  findInput.addEventListener("input", () => {
    current = 0;
    search();
    if (matches.length) go(0);
  });
  findInput.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") {
      evt.preventDefault();
      go(evt.shiftKey ? -1 : 1);
    }
  });
  replInput.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") {
      evt.preventDefault();
      replaceOne();
    }
  });
  $("#find-next").addEventListener("click", () => go(1));
  $("#find-prev").addEventListener("click", () => go(-1));
  $("#replace-one").addEventListener("click", replaceOne);
  $("#replace-all").addEventListener("click", replaceAll);
  function showReplace(open) {
    replaceRow.hidden = !open;
    findToggle.setAttribute("aria-expanded", String(open));
  }
  findToggle.addEventListener("click", () => {
    showReplace(replaceRow.hidden);
    if (!replaceRow.hidden) replInput.focus();
  });

  // ---- renaming the recording, restoring the original ---------------------------------------
  const nameBtn = $("#rename-btn");
  const nameInput = $("#rename-input");
  let renaming = false;
  function startRename() {
    renaming = true;
    nameInput.value = $("#ed-name").textContent;
    nameBtn.hidden = true;
    nameInput.hidden = false;
    nameInput.focus();
    nameInput.select();
  }
  async function endRename(keep) {
    if (!renaming) return;
    renaming = false;
    const name = nameInput.value.trim();
    nameInput.hidden = true;
    nameBtn.hidden = false;
    nameBtn.focus();
    if (!keep || !name || name === $("#ed-name").textContent) return;
    const body = new URLSearchParams({ name });
    try {
      const resp = await fetch(`/jobs/${data.job}/rename`, { method: "POST", body });
      if (!resp.ok) throw new Error();
      const saved = (await resp.json()).name;
      $("#ed-name").textContent = saved;
      document.title = `${saved} · WaveMaterial`;
      const recent = document.querySelector(".nav-recent.is-active .nav-label");
      if (recent) recent.textContent = saved;
    } catch {
      setNote("The new name could not be saved. Try again.", true);
    }
  }
  nameBtn.addEventListener("click", startRename);
  nameInput.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") {
      evt.preventDefault();
      endRename(true);
    }
  });
  nameInput.addEventListener("blur", () => endRename(true));

  // ---- history: saved versions --------------------------------------------------------------
  // Restoring (a version or the original) is an ordinary edit, so Undo brings the edits back;
  // the state it replaces is saved first as a version too, so nothing is ever lost.
  const versionList = $("#version-list");
  const versionForm = $("#version-form");
  const versionName = $("#version-name");
  async function api(url, options = {}) {
    const resp = await fetch(url, options);
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error || resp.statusText);
    return resp.status === 204 ? null : resp.json();
  }
  const postJson = (url, body) =>
    api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  function when(iso) {
    const d = new Date(iso);
    const today = new Date();
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    return d.toDateString() === today.toDateString() ? `Today, ${time}` : `${d.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
  }
  async function loadVersions() {
    try {
      const list = await api(`/jobs/${data.job}/versions`);
      const named = list.filter((v) => !v.auto);
      const autos = list.filter((v) => v.auto);
      versionList.replaceChildren(
        ...[...named, ...autos].map((v) => {
          const li = el("li", "version" + (v.auto ? " version-auto" : ""));
          const text = el("div", "version-text");
          text.append(el("strong", "", v.auto ? "Automatic: when opened" : v.name), el("span", "", when(v.created)));
          const restore = el("button", "btn btn-ghost btn-sm", "Restore");
          restore.type = "button";
          restore.dataset.restore = v.id;
          restore.dataset.name = v.auto ? "the automatic version" : `"${v.name}"`;
          const del = el("button", "icon-btn icon-btn-sm", "✕");
          del.type = "button";
          del.dataset.delete = v.id;
          del.title = "Delete this version";
          del.setAttribute("aria-label", `Delete ${v.auto ? "the automatic version" : v.name}`);
          li.append(text, restore, del);
          return li;
        }),
      );
    } catch {
      versionList.replaceChildren(el("li", "muted small", "Saved versions could not be loaded."));
    }
  }
  async function restoreFrom(url, label) {
    try {
      flushDirty(true);
      await flushSaves();
      await postJson(`/jobs/${data.job}/versions`, { name: `Before restoring ${label}` });
      const t = await api(url);
      hidePopover();
      record("restore");
      model.speakers = t.speakers;
      model.names = t.names;
      model.turns = t.turns.map((turn) => ({
        speaker: turn.speaker,
        words: turn.words.map(([text, start, end]) => ({ text, start, end })),
      }));
      renderAll(null);
      changed();
      loadVersions();
    } catch (exc) {
      setNote(`That couldn't be restored: ${exc.message}`, true);
    }
  }
  $("#save-version").addEventListener("click", () => {
    versionForm.hidden = false;
    versionName.value = "";
    versionName.focus();
  });
  $("#version-cancel").addEventListener("click", () => {
    versionForm.hidden = true;
  });
  versionForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const name = versionName.value.trim();
    if (!name) return;
    flushDirty(true);
    await flushSaves(); // the version is what's on screen
    try {
      await postJson(`/jobs/${data.job}/versions`, { name });
      versionForm.hidden = true;
      loadVersions();
    } catch (exc) {
      setNote(`The version could not be saved: ${exc.message}`, true);
    }
  });
  versionList.addEventListener("click", async (evt) => {
    const r = evt.target.closest("[data-restore]");
    const d = evt.target.closest("[data-delete]");
    if (r) restoreFrom(`/jobs/${data.job}/versions/${r.dataset.restore}`, r.dataset.name);
    if (d) {
      await api(`/jobs/${data.job}/versions/${d.dataset.delete}/delete`, { method: "POST" }).catch(() => {});
      loadVersions();
    }
  });
  $("#restore-original").addEventListener("click", () => restoreFrom(`/jobs/${data.job}/original`, "the original"));
  loadVersions();

  // ---- transcribe a passage again --------------------------------------------------------------
  // The models run on just the selected stretch; the result is a proposal to accept or not.
  // Only while no recording is being transcribed (one model at a time).
  let passageAvailable = false;
  async function checkPassage() {
    try {
      passageAvailable = (await api(`/jobs/${data.job}/passage`)).available;
    } catch {
      passageAvailable = false;
    }
  }
  checkPassage();
  setInterval(checkPassage, 5000);
  function againItem(s) {
    const item = ctxItem("Transcribe again", "", () => transcribeAgain(s), !s || !passageAvailable);
    if (!passageAvailable) item.title = "Available when no recording is being transcribed";
    checkPassage().then(() => {
      item.disabled = !s || !passageAvailable;
      item.title = passageAvailable ? "" : "Available when no recording is being transcribed";
    });
    return item;
  }
  const passageEl = $("#passage");
  let passagePoll = 0;
  function closePassage(cancel = false) {
    clearTimeout(passagePoll);
    if (cancel) fetch(`/jobs/${data.job}/passage/cancel`, { method: "POST" }).catch(() => {});
    passageEl.hidden = true;
  }
  async function transcribeAgain(s) {
    if (!s) return;
    const snap = { ...s };
    hidePopover(false);
    $("#passage-range").textContent = `${clock(s.start, true)} – ${clock(s.end, true)} · ${s.count} word${s.count === 1 ? "" : "s"}`;
    $("#passage-old").textContent = s.picked.map((w) => w.text).join(" ");
    $("#passage-busy").hidden = false;
    $("#passage-result").hidden = true;
    $("#passage-error").hidden = true;
    $("#passage-accept").hidden = true;
    passageEl.hidden = false;
    $("#passage-cancel").focus();
    const fail = (msg) => {
      $("#passage-busy").hidden = true;
      $("#passage-error").textContent = msg;
      $("#passage-error").hidden = false;
    };
    try {
      await postJson(`/jobs/${data.job}/passage`, { start: s.start, end: s.end });
    } catch (exc) {
      fail(exc.message);
      return;
    }
    const poll = async () => {
      if (passageEl.hidden) return;
      let st;
      try {
        st = await api(`/jobs/${data.job}/passage`);
      } catch {
        passagePoll = setTimeout(poll, 1000);
        return;
      }
      if (st.state === "running") {
        passagePoll = setTimeout(poll, 500);
      } else if (st.state === "failed") {
        fail(st.message);
      } else if (st.state === "done") {
        const fresh = st.words.map(([text, start, end]) => ({ text, start, end }));
        $("#passage-busy").hidden = true;
        $("#passage-new").textContent = fresh.length ? fresh.map((w) => w.text).join(" ") : "(no speech found)";
        $("#passage-result").hidden = false;
        const accept = $("#passage-accept");
        accept.hidden = false;
        accept.onclick = () => {
          closePassage();
          applyPassage(snap, fresh);
        };
        accept.focus();
      }
    };
    poll();
  }
  // Put the new words where the selected ones were. Across turns, each new word goes to the
  // turn its time falls in, so speakers are kept.
  function applyPassage(s, fresh) {
    record("transcribe-again");
    const turns = model.turns.slice();
    const bounds = [];
    for (let ti = s.from; ti <= s.to; ti++) {
      bounds.push(ti === s.from ? -Infinity : turns[ti].words[0].start);
    }
    const buckets = bounds.map(() => []);
    for (const w of fresh) {
      const mid = (w.start + w.end) / 2;
      let k = 0;
      while (k + 1 < bounds.length && bounds[k + 1] <= mid) k++;
      buckets[k].push(w);
    }
    for (let ti = s.from; ti <= s.to; ti++) {
      const before = ti === s.from ? turns[ti].words.slice(0, s.first) : [];
      const after = ti === s.to ? turns[ti].words.slice(s.last + 1) : [];
      turns[ti] = { speaker: turns[ti].speaker, words: before.concat(buckets[ti - s.from], after) };
    }
    model.turns = turns.filter((t) => t.words.length);
    renderAll(null);
    changed();
  }
  $("#passage-cancel").addEventListener("click", () => closePassage(true));

  // ---- export -------------------------------------------------------------------------------
  // In the window the server asks where to save (a native dialog); a browser downloads.
  const windowed = document.body.dataset.windowed === "yes";
  function toast(text, error = false) {
    const box = el("div", "toast" + (error ? " toast-error" : ""), text);
    $("#toast").replaceChildren(box);
    setTimeout(() => box.remove(), 5000);
  }
  $("#export-menu").addEventListener("click", async (evt) => {
    const btn = evt.target.closest("[data-export]");
    if (!btn) return;
    $("#export-menu").removeAttribute("open");
    flushDirty(true);
    await flushSaves(); // export what's on screen
    const url = `/jobs/${data.job}/export/${btn.dataset.export}`;
    if (!windowed) {
      window.location.href = url;
      return;
    }
    try {
      const resp = await fetch(url, { method: "POST" });
      const body = await resp.json().catch(() => ({}));
      if (body.cancelled) return;
      if (!resp.ok) throw new Error(body.error || "The file could not be saved.");
      toast(`Saved ${body.path}`);
    } catch (exc) {
      toast(exc.message, true);
    }
  });

  // ---- side panel ---------------------------------------------------------------------------
  const tabs = [...document.querySelectorAll('.tabs [role="tab"]')];
  function selectTab(tab) {
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    }
  }
  for (const t of tabs) {
    t.addEventListener("click", () => selectTab(t));
    t.addEventListener("keydown", (evt) => {
      const step = { ArrowLeft: -1, ArrowRight: 1 }[evt.key];
      if (!step) return;
      const next = tabs[(tabs.indexOf(t) + step + tabs.length) % tabs.length];
      selectTab(next);
      next.focus();
    });
  }
  const panelToggle = $("#panel-toggle");
  function setPanel(open) {
    editor.classList.toggle("panel-open", open);
    panelToggle.setAttribute("aria-expanded", String(open));
  }
  panelToggle.addEventListener("click", () => setPanel(!editor.classList.contains("panel-open")));

  // ---- keys ---------------------------------------------------------------------------------
  // Capture phase, so Esc closes the menu, popover, or panel before app.js leaves full screen.
  window.addEventListener(
    "keydown",
    (evt) => {
      const mod = evt.ctrlKey || evt.metaKey;
      if (evt.key === "Escape") {
        if (renaming) endRename(false);
        else if (!passageEl.hidden) closePassage(true);
        else if (!ctx.hidden) closeCtx();
        else if (!menu.hidden) closeMenu();
        else if (!pop.hidden) hidePopover();
        else if (editor.classList.contains("panel-open")) setPanel(false);
        else if (!audio.paused) audio.pause();
        else if (evt.target === findInput || evt.target === replInput) {
          findInput.value = "";
          search();
          showReplace(false);
          evt.target.blur();
        } else return;
        evt.preventDefault();
        evt.stopImmediatePropagation();
        return;
      }
      const inField = evt.target.closest?.("input, textarea, select");
      if (mod && !evt.shiftKey && (evt.key.toLowerCase() === "f" || evt.key.toLowerCase() === "h")) {
        evt.preventDefault();
        const sel = window.getSelection();
        const picked = sel.rangeCount && !sel.isCollapsed && turnsEl.contains(sel.anchorNode) ? sel.toString().trim() : "";
        if (picked && !picked.includes("\n")) {
          findInput.value = picked;
          search();
        }
        if (evt.key.toLowerCase() === "h") {
          showReplace(true);
          (picked ? replInput : findInput).focus();
        } else {
          findInput.focus();
          findInput.select();
        }
        return;
      }
      if (mod && evt.code === "Space") {
        evt.preventDefault();
        togglePlay();
      } else if (mod && evt.key.toLowerCase() === "j") {
        evt.preventDefault();
        const i = wordAt(audio.currentTime);
        if (i >= 0) keepInView(i);
        else turnsEl.children[playingTurn]?.scrollIntoView({ block: "center", behavior: "smooth" });
      } else if (mod && !inField && evt.key.toLowerCase() === "z") {
        evt.preventDefault();
        if (evt.shiftKey) redo();
        else undo();
      } else if (mod && !inField && evt.key.toLowerCase() === "y") {
        evt.preventDefault();
        redo();
      } else if (evt.key === " " && !mod && selection && !inField && !evt.target.closest?.("button")) {
        // Space plays the selection, even inside the text (it doesn't type over it).
        const sel = window.getSelection();
        if (!typing(evt.target) || !sel.isCollapsed || virtual) {
          evt.preventDefault();
          playSelection();
        }
      }
    },
    true,
  );

  // ---- start --------------------------------------------------------------------------------
  renderTurns();
  renderSpeakers();
  renderTimeline();
  updateUndo();
  loadAudio();
})();
