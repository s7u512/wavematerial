// SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
// The transcript editor: turns, speakers, the player, Follow, and select-and-listen.
// The transcript lives here, in `model`; everything on screen is rendered from it.
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const editor = $("#editor");
  if (!editor) return;

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
  const speakerColour = (id) => `var(--spk-${(Math.max(0, model.speakers.indexOf(id)) % 6) + 1})`;
  const speakerName = (id) => model.names[id] || id;
  const typing = (target) => target.closest?.("input, textarea, select, [contenteditable]");

  // ---- rendering ----------------------------------------------------------------------------
  // `flat` lists every word in reading order, with its element, for Follow and selections.
  let flat = [];

  function renderTurns() {
    flat = [];
    const frag = document.createDocumentFragment();
    model.turns.forEach((turn, ti) => {
      const art = el("div", "turn");
      art.dataset.turn = ti;
      art.style.setProperty("--spk", speakerColour(turn.speaker));
      const time = el("button", "turn-time", clock(turn.words[0].start));
      time.type = "button";
      time.title = "Play from here";
      time.dataset.seek = turn.words[0].start;
      const who = el("div", "turn-speaker", speakerName(turn.speaker));
      const text = el("p", "turn-text");
      turn.words.forEach((w, wi) => {
        if (wi) text.append(" ");
        const span = el("span", "w", w.text);
        span.dataset.i = flat.length;
        flat.push({ start: w.start, end: w.end, el: span, turn: ti });
        text.append(span);
      });
      art.append(time, who, text);
      frag.append(art);
    });
    turnsEl.replaceChildren(frag);
    spokenIndex = -1;
    playingTurn = -1;
  }

  function renderSpeakers() {
    const stats = new Map(model.speakers.map((s) => [s, { turns: 0, time: 0, longest: null }]));
    let total = 0;
    for (const turn of model.turns) {
      const st = stats.get(turn.speaker);
      if (!st) continue;
      const len = turn.words[turn.words.length - 1].end - turn.words[0].start;
      st.turns += 1;
      st.time += len;
      total += len;
      if (!st.longest || len > st.longest.len) st.longest = { start: turn.words[0].start, len };
    }
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
          row.append(play, el("span", "spk-stats", `${st.turns} turn${st.turns === 1 ? "" : "s"} · ${pct}%`));
          const bar = el("div", "spk-bar");
          const fill = el("span");
          fill.style.width = `${pct}%`;
          bar.append(fill);
          card.append(el("div", "spk-name", speakerName(s)), row, bar);
          card._sample = st.longest;
          return card;
        }),
    );
  }

  function renderTimeline() {
    const segs = [];
    for (const turn of model.turns) {
      const start = turn.words[0].start;
      const end = turn.words[turn.words.length - 1].end;
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

  // ---- audio --------------------------------------------------------------------------------
  let audioReady = false;
  let rate = 1;
  let range = null; // {start, end, loop, slow} while a selection or sample is playing

  function setNote(text, error = false) {
    note.textContent = text;
    note.classList.toggle("is-error", error);
  }

  async function loadAudio() {
    try {
      const resp = await fetch(`/jobs/${data.job}/audio/state`);
      if (!resp.ok) throw new Error(resp.statusText);
      const st = await resp.json();
      if (st.state === "ready") {
        setNote("");
        audio.src = `/jobs/${data.job}/audio`;
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
  audio.addEventListener("error", () => {
    if (audio.getAttribute("src")) setNote("The audio can't be played in this window.", true);
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
  function togglePlay() {
    if (!audioReady) return;
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
      if (range.loop) {
        audio.currentTime = range.start;
      } else {
        audio.pause();
      }
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
      flat[spokenIndex]?.el.classList.remove("is-spoken");
      flat[lit]?.el.classList.add("is-spoken");
      spokenIndex = lit;
      if (lit >= 0 && !audio.paused && !inView(flat[lit].el)) keepInView(lit);
    }
  }

  function keepInView(i) {
    const turnEl = turnsEl.children[flat[i].turn];
    const fits = turnEl.offsetHeight < scroller.clientHeight - 120;
    (fits ? turnEl : flat[i].el).scrollIntoView({ block: "center", behavior: "smooth" });
  }

  let frame = 0;
  function tick() {
    update();
    frame = audio.paused ? 0 : requestAnimationFrame(tick);
  }
  audio.addEventListener("play", () => {
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

  // ---- playing from the text ----------------------------------------------------------------
  turnsEl.addEventListener("click", (evt) => {
    const time = evt.target.closest(".turn-time");
    if (time) {
      playFrom(Number(time.dataset.seek));
      return;
    }
    const word = evt.target.closest(".w");
    if (word && (evt.ctrlKey || evt.metaKey)) {
      evt.preventDefault();
      playFrom(flat[Number(word.dataset.i)].start);
    }
  });
  const ctrlClass = (on) => turnsEl.classList.toggle("ctrl-down", on);
  document.addEventListener("keydown", (evt) => ctrlClass(evt.ctrlKey || evt.metaKey));
  document.addEventListener("keyup", (evt) => ctrlClass(evt.ctrlKey || evt.metaKey));
  window.addEventListener("blur", () => ctrlClass(false));

  $("#speaker-list").addEventListener("click", (evt) => {
    const btn = evt.target.closest("[data-sample]");
    const sample = btn?.closest(".spk-card")._sample;
    if (sample) playRange(sample.start, sample.start + Math.min(5, sample.len));
  });

  // ---- select and listen --------------------------------------------------------------------
  let selection = null; // {start, end, count}

  function selectedWords() {
    const sel = window.getSelection();
    if (!sel.rangeCount || sel.isCollapsed) return null;
    const r = sel.getRangeAt(0);
    if (!turnsEl.contains(r.commonAncestorContainer)) return null;
    const node = (n) => (n.nodeType === Node.ELEMENT_NODE ? n : n.parentElement);
    const first = node(r.startContainer).closest(".turn");
    const last = node(r.endContainer).closest(".turn");
    const from = first ? Number(first.dataset.turn) : 0;
    const to = last ? Number(last.dataset.turn) : model.turns.length - 1;
    const picked = [];
    for (let i = 0; i < flat.length; i++) {
      const w = flat[i];
      if (w.turn < from) continue;
      if (w.turn > to) break;
      if (!r.intersectsNode(w.el)) continue;
      // A range that only touches a word's edge doesn't select it.
      if (w.el.contains(r.startContainer) && r.startOffset >= w.el.textContent.length) continue;
      if (w.el.contains(r.endContainer) && r.endOffset === 0) continue;
      picked.push(i);
    }
    if (!picked.length) return null;
    const a = flat[picked[0]];
    const b = flat[picked[picked.length - 1]];
    return { start: a.start, end: b.end, count: picked.length, rect: r.getBoundingClientRect() };
  }

  function showPopover() {
    selection = selectedWords();
    const band = $("#tl-sel");
    if (!selection) {
      hidePopover(false);
      return;
    }
    $("#sel-count").textContent = `${selection.count} word${selection.count === 1 ? "" : "s"} selected`;
    $("#sel-range").textContent = `${clock(selection.start, true)} – ${clock(selection.end, true)}`;
    band.hidden = false;
    band.style.left = `${(selection.start / duration) * 100}%`;
    band.style.width = `max(2px, ${((selection.end - selection.start) / duration) * 100}%)`;
    pop.hidden = false;
    const r = selection.rect;
    const h = pop.offsetHeight;
    const top0 = scroller.getBoundingClientRect().top;
    let top = r.top - h - 10;
    if (top < top0 + 8) top = r.bottom + 10;
    pop.style.top = `${Math.round(top)}px`;
    pop.style.left = `${Math.round(Math.min(Math.max(r.left, 16), window.innerWidth - pop.offsetWidth - 16))}px`;
  }

  function hidePopover(clearSelection = true) {
    pop.hidden = true;
    selection = null;
    $("#tl-sel").hidden = true;
    if (clearSelection) window.getSelection().removeAllRanges();
  }

  let selTimer = 0;
  document.addEventListener("selectionchange", () => {
    clearTimeout(selTimer);
    selTimer = setTimeout(() => {
      if (pop.contains(document.activeElement)) return; // using the popover keeps it open
      showPopover();
    }, 120);
  });
  scroller.addEventListener("scroll", () => {
    if (!pop.hidden) hidePopover(false);
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
  // Capture phase, so Esc closes the popover or the panel before app.js leaves full screen.
  window.addEventListener(
    "keydown",
    (evt) => {
      if (evt.key === "Escape" && (!pop.hidden || editor.classList.contains("panel-open"))) {
        if (!pop.hidden) hidePopover();
        else setPanel(false);
        evt.preventDefault();
        evt.stopImmediatePropagation();
        return;
      }
      if ((evt.ctrlKey || evt.metaKey) && evt.code === "Space") {
        evt.preventDefault();
        togglePlay();
      } else if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "j") {
        evt.preventDefault();
        const i = wordAt(audio.currentTime);
        if (i >= 0) keepInView(i);
        else turnsEl.children[playingTurn]?.scrollIntoView({ block: "center", behavior: "smooth" });
      } else if (evt.key === " " && !pop.hidden && !typing(evt.target) && !evt.target.closest("button")) {
        evt.preventDefault();
        playSelection();
      }
    },
    true,
  );

  // ---- start --------------------------------------------------------------------------------
  renderTurns();
  renderSpeakers();
  renderTimeline();
  loadAudio();
})();
