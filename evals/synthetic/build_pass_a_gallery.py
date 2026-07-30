#!/usr/bin/env python3
"""Build an owner Pass A adjudication gallery from a phase-3 review JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals.synthetic.build_tasks import DEFAULT_DATASET

GALLERY_JS = r"""
(() => {
  const data = window.PASS_A_REVIEW;
  const STORAGE_KEY = `pass-a-owner-adjudications-v2:${data.source_file || data.review_type}`;
  const frames = data.frames.map((frame, index) => {
    const disagreement = (data.reviewer_disagreements || []).find(
      (row) => row.task_id === frame.task_id
    );
    return { ...frame, index, disagreement: disagreement || null };
  });

  const state = {
    filter: "escalate",
    provider: "all",
    onlyPending: false,
    cursor: 0,
    decisions: loadDecisions(),
  };

  const els = {
    stage: document.getElementById("stage"),
    media: document.getElementById("media"),
    missing: document.getElementById("missing"),
    ask: document.getElementById("ask"),
    title: document.getElementById("title"),
    subtitle: document.getElementById("subtitle"),
    aiBadge: document.getElementById("ai-badge"),
    ownerBadge: document.getElementById("owner-badge"),
    focusLabel: document.getElementById("focus-label"),
    reason: document.getElementById("reason"),
    requiredList: document.getElementById("required-list"),
    defectBlock: document.getElementById("defect-block"),
    defects: document.getElementById("defects"),
    disagreement: document.getElementById("disagreement"),
    note: document.getElementById("owner-note"),
    acceptBtn: document.getElementById("accept"),
    rejectBtn: document.getElementById("reject"),
    filmstrip: document.getElementById("filmstrip"),
    progress: document.getElementById("progress"),
    counts: document.getElementById("counts"),
    toast: document.getElementById("toast"),
  };

  function loadDecisions() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed.decisions || {};
    } catch {
      return {};
    }
  }

  function saveDecisions() {
    const payload = {
      review_type: "owner_pass_a_adjudication",
      source_review: data.source_file || data.review_type,
      adjudicator: "project owner",
      updated_at: new Date().toISOString(),
      decisions: state.decisions,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  function ownerOf(taskId) {
    return state.decisions[taskId] || null;
  }

  function visibleFrames() {
    return frames.filter((frame) => {
      if (state.filter !== "all" && frame.pass_a_decision !== state.filter) {
        return false;
      }
      if (state.provider !== "all" && frame.provider !== state.provider) {
        return false;
      }
      if (state.onlyPending && ownerOf(frame.task_id)) {
        return false;
      }
      return true;
    });
  }

  function currentFrame() {
    const list = visibleFrames();
    if (!list.length) return null;
    state.cursor = Math.max(0, Math.min(state.cursor, list.length - 1));
    return list[state.cursor];
  }

  function toast(message) {
    els.toast.textContent = message;
    els.toast.dataset.show = "1";
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      els.toast.dataset.show = "0";
    }, 1600);
  }

  function setOwnerDecision(decision) {
    const frame = currentFrame();
    if (!frame) return;
    const note = els.note.value.trim();
    state.decisions[frame.task_id] = {
      task_id: frame.task_id,
      scenario_id: frame.scenario_id,
      provider: frame.provider,
      view_id: frame.view_id,
      path: frame.path,
      ai_decision: frame.pass_a_decision,
      ai_reason: frame.pass_a_reason,
      owner_decision: decision,
      owner_reason: note || frame.pass_a_reason,
      adjudicated_at: new Date().toISOString(),
    };
    saveDecisions();
    toast(decision === "accept" ? "Accepted" : "Rejected");
    // Stay in flow: jump to the next unresolved frame in this filter.
    const list = visibleFrames();
    const nextPending = list.findIndex(
      (item, index) => index > state.cursor && !ownerOf(item.task_id)
    );
    if (nextPending >= 0) {
      state.cursor = nextPending;
    } else {
      const firstPending = list.findIndex((item) => !ownerOf(item.task_id));
      state.cursor = firstPending >= 0 ? firstPending : Math.min(state.cursor, Math.max(list.length - 1, 0));
    }
    render();
  }

  function clearOwnerDecision() {
    const frame = currentFrame();
    if (!frame || !state.decisions[frame.task_id]) return;
    delete state.decisions[frame.task_id];
    saveDecisions();
    toast("Cleared");
    render();
  }

  function move(delta) {
    const list = visibleFrames();
    if (!list.length) return;
    state.cursor = (state.cursor + delta + list.length) % list.length;
    render();
  }

  function exportPayload() {
    const decisions = Object.values(state.decisions).sort((a, b) =>
      a.task_id.localeCompare(b.task_id)
    );
    return {
      review_type: "owner_pass_a_adjudication",
      source_review: data.source_file || "phase3-pass-a-review.json",
      adjudicator: "project owner",
      adjudicated_at: new Date().toISOString(),
      counts: {
        total_recorded: decisions.length,
        accept: decisions.filter((d) => d.owner_decision === "accept").length,
        reject: decisions.filter((d) => d.owner_decision === "reject").length,
        escalate_remaining: frames.filter(
          (f) => f.pass_a_decision === "escalate" && !state.decisions[f.task_id]
        ).length,
      },
      decisions,
    };
  }

  function downloadExport() {
    const payload = exportPayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "owner-adjudications.json";
    a.click();
    URL.revokeObjectURL(url);
    toast("Exported JSON");
  }

  async function copyExport() {
    const payload = exportPayload();
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast("Copied JSON");
  }

  function badgeClass(decision) {
    if (decision === "accept") return "ok";
    if (decision === "reject") return "bad";
    return "warn";
  }

  function renderFilmstrip(list, activeId) {
    els.filmstrip.innerHTML = "";
    list.forEach((frame, i) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "thumb";
      if (frame.task_id === activeId) button.dataset.active = "1";
      const owner = ownerOf(frame.task_id);
      button.dataset.decision = owner
        ? owner.owner_decision
        : frame.pass_a_decision;
      button.innerHTML = `
        <img src="${frame.image_src}" alt="" loading="lazy">
        <span>${frame.scenario_id} · ${frame.view_id}</span>
      `;
      button.addEventListener("click", () => {
        state.cursor = i;
        render();
      });
      els.filmstrip.appendChild(button);
    });
  }

  function render() {
    const list = visibleFrames();
    const decided = Object.keys(state.decisions).length;
    const escalateOpen = frames.filter(
      (f) => f.pass_a_decision === "escalate" && !state.decisions[f.task_id]
    ).length;
    els.counts.textContent = `${data.counts.escalate} escalate · ${data.counts.reject} reject · ${data.counts.accept} accept · ${decided} owner decisions · ${escalateOpen} escalations left`;

    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.dataset.active = button.dataset.filter === state.filter ? "1" : "0";
    });
    document.querySelectorAll("[data-provider]").forEach((button) => {
      button.dataset.active =
        button.dataset.provider === state.provider ? "1" : "0";
    });
    document.getElementById("pending-only").dataset.active = state.onlyPending
      ? "1"
      : "0";

    if (!list.length) {
      els.progress.textContent = "0 / 0";
      els.ask.textContent = "Queue clear";
      els.title.textContent = "Nothing to review";
      els.subtitle.textContent = "Nothing matches this filter.";
      els.media.hidden = true;
      els.missing.hidden = false;
      els.missing.textContent = "No frames in this view.";
      els.filmstrip.innerHTML = "";
      els.focusLabel.textContent = "Focus";
      els.reason.textContent = "—";
      els.requiredList.innerHTML = "";
      els.defectBlock.hidden = true;
      els.disagreement.hidden = true;
      els.ownerBadge.hidden = true;
      return;
    }

    const frame = currentFrame();
    const decision = frame.pass_a_decision;
    const prompt = {
      escalate: {
        ask: "Does this frame clear Pass A?",
        focus: "Check this uncertainty in the photo",
        accept: "Accept · A",
        reject: "Reject · R",
      },
      reject: {
        ask: "Was the AI reject right?",
        focus: "Confirm this reject reason, or overturn it",
        accept: "Overturn · A",
        reject: "Keep reject · R",
      },
      accept: {
        ask: "Spot-check: still accept?",
        focus: "AI accepted — look for a hard fail only",
        accept: "Keep accept · A",
        reject: "Reject · R",
      },
    }[decision] || {
      ask: "Does this frame clear Pass A?",
      focus: "What to verify",
      accept: "Accept · A",
      reject: "Reject · R",
    };

    els.progress.textContent = `${state.cursor + 1} / ${list.length}`;
    els.ask.textContent = prompt.ask;
    els.title.textContent = `${frame.scenario_id} · ${frame.room_type}`;
    els.subtitle.textContent = `${frame.provider} · ${frame.view_id}`;
    els.aiBadge.textContent = `AI ${decision}`;
    els.aiBadge.className = `badge ${badgeClass(decision)}`;
    els.focusLabel.textContent = prompt.focus;
    els.acceptBtn.textContent = prompt.accept;
    els.rejectBtn.textContent = prompt.reject;

    const owner = ownerOf(frame.task_id);
    if (owner && owner.owner_decision) {
      els.ownerBadge.hidden = false;
      els.ownerBadge.textContent = `You: ${owner.owner_decision}`;
      els.ownerBadge.className = `badge ${badgeClass(owner.owner_decision)}`;
      els.note.value = owner.owner_reason || "";
    } else {
      els.ownerBadge.hidden = true;
      els.ownerBadge.textContent = "";
      els.note.value = "";
    }

    els.reason.textContent = frame.pass_a_reason || "No AI reason recorded.";
    const requiredItems = (frame.required || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    els.requiredList.replaceChildren();
    if (!requiredItems.length) {
      const empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "None listed";
      els.requiredList.appendChild(empty);
    } else {
      for (const item of requiredItems) {
        const li = document.createElement("li");
        li.textContent = item;
        els.requiredList.appendChild(li);
      }
    }

    const defects = (frame.intended_defects || "").trim();
    const hasDefect = defects && defects.toLowerCase() !== "none";
    els.defectBlock.hidden = !hasDefect;
    els.defects.textContent = defects || "none";

    if (frame.disagreement) {
      els.disagreement.hidden = false;
      const firstReason = frame.first_review?.reason || "No reason recorded.";
      const secondReason = frame.second_review?.reason || "No reason recorded.";
      els.disagreement.textContent =
        `Reviewers disagreed: ${frame.disagreement.first} vs ${frame.disagreement.second} → escalated\n\n` +
        `First review: ${firstReason}\n\nSecond review: ${secondReason}`;
    } else {
      els.disagreement.hidden = true;
    }
    els.media.hidden = false;
    els.missing.hidden = true;
    els.media.src = frame.image_src;
    els.media.alt = frame.task_id;
    renderFilmstrip(list, frame.task_id);
    const activeThumb = els.filmstrip.querySelector('[data-active="1"]');
    if (activeThumb) {
      const left =
        activeThumb.offsetLeft -
        (els.filmstrip.clientWidth - activeThumb.clientWidth) / 2;
      els.filmstrip.scrollTo({
        left: Math.max(0, left),
        behavior: "smooth",
      });
    }
  }

  document.querySelectorAll("[data-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      state.cursor = 0;
      render();
    });
  });
  document.querySelectorAll("[data-provider]").forEach((button) => {
    button.addEventListener("click", () => {
      state.provider = button.dataset.provider;
      state.cursor = 0;
      render();
    });
  });
  document.getElementById("pending-only").addEventListener("click", () => {
    state.onlyPending = !state.onlyPending;
    state.cursor = 0;
    render();
  });
  document.getElementById("prev").addEventListener("click", () => move(-1));
  document.getElementById("next").addEventListener("click", () => move(1));
  document
    .getElementById("accept")
    .addEventListener("click", () => setOwnerDecision("accept"));
  document
    .getElementById("reject")
    .addEventListener("click", () => setOwnerDecision("reject"));
  document
    .getElementById("clear")
    .addEventListener("click", () => clearOwnerDecision());
  document
    .getElementById("export")
    .addEventListener("click", () => downloadExport());
  document.getElementById("copy").addEventListener("click", () => copyExport());
  els.note.addEventListener("change", () => {
    const frame = currentFrame();
    const owner = frame && ownerOf(frame.task_id);
    if (!owner) return;
    owner.owner_reason = els.note.value.trim() || owner.ai_reason;
    owner.adjudicated_at = new Date().toISOString();
    saveDecisions();
  });

  window.addEventListener("keydown", (event) => {
    if (
      event.target instanceof HTMLTextAreaElement ||
      event.target instanceof HTMLInputElement
    ) {
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "arrowright" || key === "j") {
      event.preventDefault();
      move(1);
    } else if (key === "arrowleft" || key === "k") {
      event.preventDefault();
      move(-1);
    } else if (key === "a") {
      event.preventDefault();
      setOwnerDecision("accept");
    } else if (key === "r") {
      event.preventDefault();
      setOwnerDecision("reject");
    } else if (key === "u" || key === "backspace") {
      event.preventDefault();
      clearOwnerDecision();
    } else if (key === "1") {
      state.filter = "escalate";
      state.cursor = 0;
      render();
    } else if (key === "2") {
      state.filter = "reject";
      state.cursor = 0;
      render();
    } else if (key === "3") {
      state.filter = "accept";
      state.cursor = 0;
      render();
    } else if (key === "0") {
      state.filter = "all";
      state.cursor = 0;
      render();
    } else if (key === "e" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      downloadExport();
    }
  });

  render();
})();
"""

GALLERY_CSS = r"""
:root {
  --paper: #f6f3ec;
  --panel: #fffdf8;
  --panel-muted: #f1ede3;
  --ink: #22262d;
  --muted: #626b76;
  --line: #e4dfd3;
  --brass: #9a7729;
  --brass-deep: #7d5e1b;
  --ok: #1d6f4c;
  --warn: #8a6a1f;
  --bad: #a3312a;
  --media: #0e1116;
  --shadow: 0 18px 40px rgba(34, 38, 45, 0.08);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
  --sans: "Avenir Next", Avenir, "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  --serif: Fraunces, "New York", "Iowan Old Style", Palatino, Charter, Georgia, serif;
}
* { box-sizing: border-box; }
html, body {
  height: 100%;
  max-width: 100%;
  overflow-x: hidden;
}
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(154, 119, 41, 0.08), transparent 60%),
    linear-gradient(180deg, #f8f5ef 0%, var(--paper) 40%, #f3efe6 100%);
  font: 14px/1.55 var(--sans);
}
button, textarea { font: inherit; color: inherit; }
button {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 7px;
  padding: 10px 14px;
  min-height: 44px;
  cursor: pointer;
  transition: background 180ms var(--ease), border-color 180ms var(--ease), transform 180ms var(--ease);
}
button:hover { border-color: #d2c9b5; }
button:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
button[data-active="1"] {
  border-color: var(--brass);
  background: var(--primary-soft, #f0e7d2);
  color: var(--brass-deep);
}
button.primary {
  background: var(--brass);
  border-color: var(--brass);
  color: var(--panel);
}
button.primary:hover { background: var(--brass-deep); border-color: var(--brass-deep); }
button.danger {
  background: color-mix(in srgb, var(--bad) 10%, white);
  border-color: color-mix(in srgb, var(--bad) 35%, white);
  color: var(--bad);
}
button.ghost { background: transparent; }
.app {
  min-height: 100%;
  width: 100%;
  max-width: 100vw;
  display: grid;
  grid-template-rows: auto 1fr auto;
  overflow-x: hidden;
}
.top {
  display: grid;
  gap: 16px;
  padding: 20px 28px 14px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  backdrop-filter: blur(10px);
  position: sticky;
  top: 0;
  z-index: 5;
}
@media (min-width: 1100px) {
  .top {
    grid-template-columns: minmax(280px, 1fr) auto;
    align-items: end;
    justify-content: space-between;
  }
}
.controls { display: grid; gap: 10px; justify-items: start; }
@media (min-width: 1100px) {
  .controls { justify-items: end; }
}
.brand h1 {
  margin: 0;
  font: 600 28px/1.2 var(--serif);
  letter-spacing: -0.02em;
  text-wrap: balance;
}
.brand p {
  margin: 4px 0 0;
  color: var(--muted);
  max-width: 62ch;
}
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.hint {
  color: var(--muted);
  font-size: 12.5px;
}
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.75fr);
  gap: 20px;
  padding: 20px 28px;
  align-items: stretch;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.stage {
  background: var(--media);
  border-radius: 14px;
  width: 100%;
  min-width: 0;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  box-shadow: var(--shadow);
  position: relative;
  align-self: start;
}
.stage img {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: min(70vh, 760px);
  object-fit: contain;
}
.stage .missing {
  color: #c9c4b8;
  padding: 40px;
  text-align: center;
}
.rail {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px 18px 16px;
  display: grid;
  gap: 12px;
  align-content: start;
  box-shadow: var(--shadow);
  position: sticky;
  top: 108px;
  min-width: 0;
}
.ask {
  margin: 0;
  font: 600 22px/1.25 var(--serif);
  letter-spacing: -0.02em;
  text-wrap: balance;
  color: var(--ink);
}
.identity-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  align-items: center;
  justify-content: space-between;
}
.identity {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.identity h2 {
  margin: 0;
  font: 600 13px/1.35 var(--sans);
  color: var(--muted);
}
.rail .subtitle {
  margin: 0;
  color: var(--muted);
  font-size: 12.5px;
}
.badges { display: flex; flex-wrap: wrap; gap: 8px; }
.rail details.secondary {
  border-top: 1px solid var(--line);
  padding-top: 8px;
}
.rail details.secondary summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 12.5px;
  font-weight: 600;
}
.rail details.secondary[open] summary { margin-bottom: 10px; }
.rail details.secondary ol {
  margin: 10px 0 0;
  padding-left: 1.2rem;
  color: var(--muted);
  font-size: 12.5px;
}
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  border: 1px solid transparent;
}
.badge.ok { background: color-mix(in srgb, var(--ok) 12%, white); color: var(--ok); }
.badge.warn { background: color-mix(in srgb, var(--warn) 14%, white); color: var(--warn); }
.badge.bad { background: color-mix(in srgb, var(--bad) 12%, white); color: var(--bad); }
.focus {
  padding: 14px 14px 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--warn) 12%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--warn) 28%, var(--line));
}
.focus-label {
  margin: 0 0 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: #6d5418;
  letter-spacing: 0.01em;
}
.focus-body {
  margin: 0;
  font-size: 16px;
  line-height: 1.4;
  color: var(--ink);
  text-wrap: pretty;
}
.section {
  display: grid;
  gap: 8px;
}
.section-label {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
}
#required-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
#required-list li {
  margin: 0;
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--panel-muted);
  border: 1px solid var(--line);
  font-size: 12.5px;
  color: var(--ink);
}
#required-list li.empty {
  background: transparent;
  border-style: dashed;
  color: var(--muted);
}
.defect-block[hidden],
.disagreement[hidden],
#owner-badge[hidden] {
  display: none !important;
}
.defect-block {
  padding: 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bad) 8%, var(--panel));
  border: 1px solid color-mix(in srgb, var(--bad) 22%, var(--line));
}
.defect-block .section-label { color: var(--bad); }
.defect-block p:last-child {
  margin: 0;
  font-size: 14px;
  line-height: 1.4;
  color: var(--ink);
}
.disagreement {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--panel-muted);
  color: #6d5418;
  font-size: 12.5px;
  line-height: 1.4;
  white-space: pre-wrap;
}
.note-block {
  display: grid;
  gap: 6px;
  padding-top: 4px;
  border-top: 1px solid var(--line);
}
.note-block label {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--muted);
}
textarea {
  width: 100%;
  min-height: 64px;
  resize: vertical;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 10px 12px;
  background: var(--paper);
}
.actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding-top: 2px;
}
.actions .primary,
.actions .danger {
  min-height: 48px;
  font-weight: 600;
}
.nav {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 8px;
  align-items: center;
}
.nav #progress {
  text-align: center;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  font-weight: 600;
}
.film {
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  padding: 14px 28px 18px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  overflow: hidden;
}
.film-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
  margin-bottom: 10px;
}
.film-head strong { font: 600 16px/1.3 var(--serif); }
.film-head span { color: var(--muted); font-size: 12.5px; }
#filmstrip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
  scroll-snap-type: x mandatory;
  min-width: 0;
  max-width: 100%;
}
.thumb {
  flex: 0 0 auto;
  width: 148px;
  padding: 0;
  overflow: hidden;
  border-radius: 10px;
  background: var(--panel);
  scroll-snap-align: start;
  text-align: left;
}
.thumb img {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 2;
  object-fit: cover;
  background: #d9d4c8;
}
.thumb span {
  display: block;
  padding: 8px 10px 10px;
  font-size: 12px;
  color: var(--muted);
}
.thumb[data-active="1"] { border-color: var(--brass); box-shadow: inset 0 0 0 1px var(--brass); }
.thumb[data-decision="accept"] span { color: var(--ok); }
.thumb[data-decision="reject"] span { color: var(--bad); }
.thumb[data-decision="escalate"] span { color: var(--warn); }
.toast {
  position: fixed;
  right: 24px;
  bottom: 24px;
  background: var(--ink);
  color: var(--panel);
  padding: 10px 14px;
  border-radius: 999px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 180ms var(--ease), transform 180ms var(--ease);
  pointer-events: none;
  z-index: 20;
}
.toast[data-show="1"] {
  opacity: 1;
  transform: translateY(0);
}
@media (max-width: 980px) {
  .workspace {
    grid-template-columns: 1fr;
  }
  .controls { justify-items: start; }
  .stage { min-height: 42vh; order: 1; }
  .stage img { max-height: 42vh; }
  .rail {
    position: static;
    order: 2;
  }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; scroll-behavior: auto !important; }
}
"""


def _image_src(dataset_dir: Path, output: Path, path_value: str) -> str:
    # Review JSON may store repo-relative Windows paths. Prefer paths relative
    # to the gallery HTML so file:// and local static servers both work.
    parts = Path(str(path_value).replace("\\", "/")).parts
    if "images" in parts:
        image = dataset_dir.joinpath(*parts[parts.index("images") :])
    else:
        candidate = dataset_dir / path_value
        image = candidate if candidate.exists() else Path(path_value)
    return Path(os.path.relpath(image.resolve(), output.parent.resolve())).as_posix()


def build(dataset_dir: Path, review_path: Path, output: Path) -> None:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("status") == "partial":
        raise ValueError("Pass A review is partial and cannot populate the gallery")
    scenario_views: dict[tuple[str, str], dict[str, object]] = {}
    for scenario_path in (dataset_dir / "scenarios").glob("*.json"):
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        for view in scenario.get("views") or []:
            scenario_views[(scenario["id"], view["id"])] = view
    frames = []
    for frame in review["frames"]:
        item = dict(frame)
        if "path" not in item and "image_path" in item:
            item["path"] = item["image_path"]
        view = scenario_views.get((item["scenario_id"], item["view_id"]), {})
        if "required" not in item:
            required = view.get("intended_visible_items") or []
            item["required"] = ", ".join(str(value) for value in required)
        if "intended_defects" not in item:
            defects = view.get("intended_defects") or []
            item["intended_defects"] = "; ".join(str(value) for value in defects)
        first = item.get("first_review") or {}
        second = item.get("second_review") or {}
        if first or second:
            first_decision = first.get("decision")
            second_decision = second.get("decision")
            item["pass_a_reason"] = (
                first.get("reason")
                if first_decision == second_decision
                else "Independent reviewers disagreed: "
                f"{first_decision} vs {second_decision}"
            )
        item["image_src"] = _image_src(dataset_dir, output, item["path"])
        frames.append(item)
    disagreements = list(review.get("reviewer_disagreements", []))
    for frame in frames:
        first = frame.get("first_review") or {}
        second = frame.get("second_review") or {}
        if first and second and first.get("decision") != second.get("decision"):
            disagreements.append(
                {
                    "task_id": frame["task_id"],
                    "first": first.get("decision"),
                    "second": second.get("decision"),
                }
            )
    payload = {
        "review_type": review.get("review_type"),
        "reviewed_at": review.get("reviewed_at"),
        "source_file": review_path.name,
        "counts": {
            decision: int((review.get("counts") or {}).get(decision, 0))
            for decision in ("accept", "reject", "escalate")
        },
        "owner_escalations_priority": review.get("owner_escalations_priority", []),
        "reviewer_disagreements": disagreements,
        "frames": frames,
    }
    priority = "".join(
        f"<li>{_escape(item)}</li>" for item in payload["owner_escalations_priority"]
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pass A owner gallery</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&display=swap" rel="stylesheet">
<style>{GALLERY_CSS}</style>
</head>
<body>
<div class="app">
  <header class="top">
    <div class="brand">
      <h1>Pass A owner gallery</h1>
      <p>Default queue is escalate-to-owner. Scan rejects when you want a fast second look. Decisions stay in this browser until you export JSON and apply it.</p>
    </div>
    <div class="controls">
      <div class="row">
        <button type="button" data-filter="escalate">Escalate</button>
        <button type="button" data-filter="reject">Reject</button>
        <button type="button" data-filter="accept">Accept</button>
        <button type="button" data-filter="all">All</button>
        <button type="button" id="pending-only">Owner pending</button>
      </div>
      <div class="row">
        <button type="button" data-provider="all">All providers</button>
        <button type="button" data-provider="Google">Google</button>
        <button type="button" data-provider="OpenAI">OpenAI</button>
        <button type="button" id="export" class="primary">Export JSON</button>
        <button type="button" id="copy" class="ghost">Copy JSON</button>
      </div>
      <div class="hint">Keys: ←/→ or J/K · A accept · R reject · U clear · 1 escalate · 2 reject · 3 accept</div>
      <div class="hint" id="counts"></div>
    </div>
  </header>

  <main class="workspace">
    <section class="stage" id="stage" aria-label="Evidence">
      <img id="media" alt="">
      <div class="missing" id="missing" hidden>No frame selected</div>
    </section>
    <aside class="rail" aria-label="Decision">
      <p class="ask" id="ask">Loading review…</p>
      <div class="identity-row">
        <div class="identity">
          <h2 id="title">Loading</h2>
          <p class="subtitle" id="subtitle"></p>
        </div>
        <div class="badges">
          <span class="badge warn" id="ai-badge">AI</span>
          <span class="badge ok" id="owner-badge" hidden></span>
        </div>
      </div>
      <section class="focus" aria-labelledby="focus-label">
        <p class="focus-label" id="focus-label">Check this uncertainty in the photo</p>
        <p class="focus-body" id="reason">—</p>
      </section>
      <section class="section" aria-labelledby="required-label">
        <p class="section-label" id="required-label">Must be visible</p>
        <ul id="required-list"></ul>
      </section>
      <section class="defect-block" id="defect-block" hidden aria-labelledby="defect-label">
        <p class="section-label" id="defect-label">Intended defect to evidence</p>
        <p id="defects"></p>
      </section>
      <div class="disagreement" id="disagreement" hidden></div>
      <div class="actions">
        <button type="button" id="accept" class="primary">Accept · A</button>
        <button type="button" id="reject" class="danger">Reject · R</button>
      </div>
      <div class="nav">
        <button type="button" id="prev">Previous</button>
        <div id="progress">0 / 0</div>
        <button type="button" id="next">Next</button>
      </div>
      <details class="secondary">
        <summary>Note / clear / priority</summary>
        <div class="note-block">
          <label>
            Optional note
            <textarea id="owner-note" placeholder="Only if you need to explain the decision"></textarea>
          </label>
          <button type="button" id="clear" class="ghost">Clear owner decision</button>
        </div>
        <ol>{priority or "<li>None listed</li>"}</ol>
        <p class="hint">Apply export with:<br>
        <code>.\\.venv\\Scripts\\python.exe -m evals.synthetic.apply_owner_adjudications owner-adjudications.json</code></p>
      </details>
    </aside>
  </main>

  <section class="film" aria-label="Queue filmstrip">
    <div class="film-head">
      <strong>Queue</strong>
      <span>Click any frame to jump. Colour marks AI or owner decision.</span>
    </div>
    <div id="filmstrip"></div>
  </section>
</div>
<div class="toast" id="toast" data-show="0"></div>
<script>window.PASS_A_REVIEW = {json.dumps(payload, ensure_ascii=True)};</script>
<script>{GALLERY_JS}</script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET,
    )
    parser.add_argument(
        "--review",
        type=Path,
        help=(
            "Pass A review JSON (default: newest initial or retry "
            "phase3 review)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Gallery HTML path",
    )
    args = parser.parse_args()
    dataset_dir = args.dataset_dir
    review = args.review
    if review is None:
        candidates = sorted(
            [
                *dataset_dir.joinpath("reports").glob(
                    "phase3-pass-a-review-*.json"
                ),
                *dataset_dir.joinpath("reports").glob(
                    "phase3-retry-pass-a-review-*.json"
                ),
            ],
            key=lambda path: path.stat().st_mtime_ns,
        )
        if not candidates:
            raise SystemExit("No phase3-pass-a-review-*.json found; pass --review")
        review = candidates[-1]
    output = args.output or dataset_dir / "reports" / "pass-a-owner-gallery.html"
    build(dataset_dir, review, output)
    print(f"Wrote {output} from {review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
