// SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
// WaveMaterial page behaviour. No inline scripts: the page's CSP allows only this file and htmx.
"use strict";

(function () {
  const $ = (sel, root = document) => root.querySelector(sel);

  // ---- polling: don't refresh a list while one of its menus is open ------------------------
  document.addEventListener("htmx:beforeRequest", (evt) => {
    const el = evt.detail.elt;
    if (el.hasAttribute("data-poll") && evt.detail.requestConfig.triggeringEvent?.type !== "refresh") {
      if (document.querySelector("details.menu[open]") || document.activeElement?.closest?.(".tags")) {
        evt.preventDefault();
      }
    }
  });

  // Open a row menu upwards when there isn't room for it below.
  document.addEventListener("toggle", (evt) => {
    const menu = evt.target;
    if (!menu.matches?.("details.menu") || !menu.open) return;
    menu.classList.remove("menu-up");
    const list = menu.querySelector("ul");
    if (list && list.getBoundingClientRect().bottom > window.innerHeight - 8) menu.classList.add("menu-up");
  }, true);

  // Close an open row menu when clicking elsewhere or after choosing an item.
  document.addEventListener("click", (evt) => {
    document.querySelectorAll("details.menu[open]").forEach((d) => {
      if (!d.contains(evt.target) || evt.target.closest("li button")) d.removeAttribute("open");
    });
  });

  // ---- "Copy log": a job's report, ready to paste into an issue ----------------------------
  // The clipboard API first; then the older copy command (WebKitGTK may lack the API); if
  // both fail, say so (the log file can still be opened).
  function copyText(text) {
    if (navigator.clipboard?.writeText) {
      return navigator.clipboard.writeText(text).then(() => true, () => copyByCommand(text));
    }
    return Promise.resolve(copyByCommand(text));
  }

  function copyByCommand(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    area.remove();
    return ok;
  }

  document.addEventListener("click", async (evt) => {
    const button = evt.target.closest("[data-copy-report]");
    if (!button) return;
    const label = button.textContent;
    button.disabled = true;
    let ok = false;
    try {
      const resp = await fetch(button.dataset.copyReport, { credentials: "same-origin" });
      ok = resp.ok && (await copyText(await resp.text()));
    } catch (e) {
      ok = false;
    }
    button.textContent = ok ? "Copied" : "Couldn't copy: use Open log file";
    setTimeout(() => {
      button.textContent = label;
      button.disabled = false;
    }, ok ? 1500 : 4000);
  });

  // ---- full screen (F11; Esc leaves it when there is nothing else to close) ----------------
  document.addEventListener("keydown", (evt) => {
    if (evt.key === "F11") {
      const hint = $("#f11");
      if (hint) {
        evt.preventDefault();
        hint.click();
      }
    }
    if (evt.key === "Escape") {
      if ($("#modal").children.length) closeModal();
      else if ($("#drawer").children.length) closeDrawer();
      else if ($("#f11")?.dataset.full === "yes" && !evt.target.closest("input, textarea, select, [contenteditable]")) {
        $("#f11").click();
      }
    }
  });

  // ---- browser mode: tell the app a page is still open (it exits a while after the last) ---
  if (document.body.dataset.windowed === "no") {
    setInterval(() => fetch("/alive", { cache: "no-store" }).catch(() => {}), 30000);
  }

  // ---- draggable dividers: sidebar | content, and transcript | side panel in the editor -----
  // Widths are saved in settings (the window forgets browser storage between launches).
  const DIVIDERS = [
    { id: "divider-sidebar", setting: "sidebar_width", prop: "--sidebar-w", def: 248, min: 160, max: 480,
      target: () => document.documentElement, width: (x) => x },
    { id: "divider-panel", setting: "panel_width", prop: "--panel-w", def: 340, min: 260, max: 640,
      target: () => document.getElementById("editor"), width: (x) => window.innerWidth - x },
  ];
  function saveWidth(setting, value) {
    fetch("/settings/ui", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [setting]: value }),
    }).catch(() => {});
  }
  for (const d of DIVIDERS) {
    const bar = document.getElementById(d.id);
    const target = d.target();
    if (!bar || !target) continue;
    const current = () => parseInt(getComputedStyle(target).getPropertyValue(d.prop), 10) || d.def;
    const limit = (w) => {
      let max = d.max;
      if (d.id === "divider-panel") { // keep the transcript readable
        const side = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-w"), 10) || 248;
        max = Math.min(max, window.innerWidth - side - 420);
      }
      return Math.round(Math.min(Math.max(w, d.min), Math.max(d.min, max)));
    };
    const set = (w) => {
      target.style.setProperty(d.prop, `${limit(w)}px`);
      bar.setAttribute("aria-valuenow", String(limit(w)));
    };
    bar.setAttribute("aria-valuemin", String(d.min));
    bar.setAttribute("aria-valuemax", String(d.max));
    bar.setAttribute("aria-valuenow", String(current()));
    bar.addEventListener("pointerdown", (evt) => {
      bar.setPointerCapture(evt.pointerId);
      bar.classList.add("is-dragging");
      document.body.classList.add("is-resizing");
    });
    bar.addEventListener("pointermove", (evt) => {
      if (bar.hasPointerCapture(evt.pointerId)) set(d.width(evt.clientX));
    });
    bar.addEventListener("pointerup", (evt) => {
      if (!bar.hasPointerCapture(evt.pointerId)) return;
      bar.releasePointerCapture(evt.pointerId);
      bar.classList.remove("is-dragging");
      document.body.classList.remove("is-resizing");
      saveWidth(d.setting, current());
    });
    bar.addEventListener("dblclick", () => {
      target.style.removeProperty(d.prop);
      bar.setAttribute("aria-valuenow", String(current()));
      saveWidth(d.setting, 0);
    });
    bar.addEventListener("keydown", (evt) => {
      const step = { ArrowLeft: -16, ArrowRight: 16 }[evt.key];
      if (!step) return;
      evt.preventDefault();
      set(current() + (d.id === "divider-panel" ? -step : step)); // the panel grows leftwards
      saveWidth(d.setting, current());
    });
  }

  // ---- drawer and modal --------------------------------------------------------------------
  function closeDrawer() { $("#drawer").replaceChildren(); }
  function closeModal() { $("#modal").replaceChildren(); }
  document.addEventListener("click", (evt) => {
    if (evt.target.closest("[data-close-drawer]")) closeDrawer();
    if (evt.target.closest("[data-close-modal]")) closeModal();
  });
  document.body.addEventListener("close-drawer", closeDrawer);
  document.body.addEventListener("close-modal", closeModal);
  document.addEventListener("htmx:afterSwap", (evt) => {
    if (evt.detail.target.id === "drawer") $("#drawer .drawer")?.focus();
    if (evt.detail.target.id === "modal") $("#modal .modal-card")?.focus();
    updateAddCount();
  });

  // ---- errors ------------------------------------------------------------------------------
  let toastTimer;
  function toast(text) {
    const box = $("#toast");
    box.innerHTML = "";
    const div = document.createElement("div");
    div.className = "toast";
    div.textContent = text;
    box.appendChild(div);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.replaceChildren(), 5000);
  }
  document.addEventListener("htmx:responseError", (evt) => {
    const msg = evt.detail.xhr.responseText.replace(/<[^>]*>/g, "").trim();
    toast(msg || "Something went wrong. See the log for details.");
  });
  document.addEventListener("htmx:sendError", () => {
    if (!document.querySelector("[data-poll]")) toast("WaveMaterial is not responding.");
  });

  // ---- tag inputs (key terms) --------------------------------------------------------------
  function addTag(box, value) {
    value = value.trim().replace(/,$/, "").trim();
    if (!value) return;
    const name = box.dataset.name;
    const existing = [...box.querySelectorAll("input[type=hidden]")].map((i) => i.value.toLowerCase());
    if (existing.includes(value.toLowerCase())) return;
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.append(value);
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = name;
    hidden.value = value;
    const x = document.createElement("button");
    x.type = "button";
    x.className = "tag-x";
    x.setAttribute("aria-label", `Remove ${value}`);
    x.innerHTML = '<svg class="i" width="12" height="12" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8 M12 4l-8 8"/></svg>';
    tag.append(hidden, x);
    box.insertBefore(tag, box.querySelector(".tag-entry"));
    changed(box);
  }
  function changed(box) {
    box.closest("form")?.dispatchEvent(new Event("change", { bubbles: true }));
  }
  document.addEventListener("keydown", (evt) => {
    const entry = evt.target.closest?.(".tag-entry");
    if (!entry) return;
    const box = entry.closest("[data-tags]");
    if (evt.key === "Enter" || evt.key === ",") {
      evt.preventDefault();
      addTag(box, entry.value);
      entry.value = "";
    } else if (evt.key === "Backspace" && !entry.value) {
      const tags = box.querySelectorAll(".tag");
      if (tags.length) { tags[tags.length - 1].remove(); changed(box); }
    }
  });
  document.addEventListener("focusout", (evt) => {
    const entry = evt.target.closest?.(".tag-entry");
    if (entry && entry.value.trim()) {
      addTag(entry.closest("[data-tags]"), entry.value);
      entry.value = "";
    }
  });
  document.addEventListener("click", (evt) => {
    const x = evt.target.closest(".tag-x");
    if (x) {
      const box = x.closest("[data-tags]");
      x.closest(".tag").remove();
      changed(box);
    }
  });
  // Typing in the tag box must not post the settings form on every keystroke.
  document.addEventListener("change", (evt) => {
    if (evt.target.classList?.contains("tag-entry")) evt.stopPropagation();
  }, true);

  // ---- add recordings ----------------------------------------------------------------------
  function updateAddCount() {
    const list = $("#add-files");
    const submit = $("#add-submit");
    const later = $("#add-later");
    if (!list || !submit) return;
    const n = list.querySelectorAll(".file-row").length;
    list.dataset.count = String(n);
    submit.disabled = n === 0;
    if (later) later.disabled = n === 0;
  }
  document.addEventListener("click", (evt) => {
    const rm = evt.target.closest("[data-remove-file]");
    if (rm) { rm.closest(".file-row").remove(); updateAddCount(); }
    if (evt.target.closest("#typed-add")) addPaths([$("#typed-path").value], "typed");
  });
  document.addEventListener("keydown", (evt) => {
    if (evt.target.id === "typed-path" && evt.key === "Enter") {
      evt.preventDefault();
      addPaths([evt.target.value], "typed");
    }
  });
  function addPaths(paths, how) {
    paths = paths.map((p) => p.trim()).filter(Boolean);
    if (!paths.length) return;
    const current = [...document.querySelectorAll("#add-files input[name=paths]")].map((i) => i.value);
    htmx.ajax("POST", "/add/files", {
      target: "#add-files",
      swap: "outerHTML",
      values: { how, dropped: JSON.stringify(paths), paths: current },
    });
    const typed = $("#typed-path");
    if (typed) typed.value = "";
  }
  document.addEventListener("dragover", (evt) => {
    const zone = evt.target.closest?.("#dropzone");
    if (zone) { evt.preventDefault(); zone.classList.add("is-over"); }
  });
  document.addEventListener("dragleave", (evt) => {
    evt.target.closest?.("#dropzone")?.classList.remove("is-over");
  });
  // In the app window, dropped files reach Python (which alone sees full paths) and come
  // back through wmAddDropped. A plain browser can't see paths, so it says so instead.
  document.addEventListener("drop", (evt) => {
    evt.preventDefault();
    $("#dropzone")?.classList.remove("is-over");
    if (document.body.dataset.windowed !== "yes") {
      toast("Dropping files needs the WaveMaterial window. Type the path instead.");
    }
  });
  document.addEventListener("dragover", (evt) => evt.preventDefault());
  window.wmAddDropped = (paths) => {
    if ($("#add-files")) { addPaths(paths, "drop"); return; }
    htmx.ajax("GET", "/add", { target: "#modal" }).then(() => addPaths(paths, "drop"));
  };
})();
