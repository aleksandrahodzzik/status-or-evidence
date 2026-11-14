(function () {
  "use strict";
  const D = window.SOR_DATA;
  const EV = { bare: "Bare claim", evidence: "3 feature z-scores", atlas: "Atlas similarities" };
  const AUTH = { high: "Senior PI", low: "Junior reviewer" };
  const COL = { green: "#16a34a", red: "#e11d48", slate: "#475569", grid: "#e2e8f0", ink: "#0f172a", muted: "#64748b" };
  const NS = "http://www.w3.org/2000/svg";
  const state = { model: "contributor", variant: "with_nsc" };

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (x, d = 1) => (x * 100).toFixed(d).replace(/\.0$/, "") + "%";
  const FOLLOWUP = {
    "followup-tool": { auth: null, label: "Follow-up · pipeline sends the full atlas comparison" },
    "followup-share": { auth: "high", label: "Follow-up · senior PI shares the full atlas comparison" },
    "followup-dispute-high": { auth: "high", dir: "correct", label: "Follow-up · senior PI disputes, with the full atlas comparison" },
    "followup-dispute-low": { auth: "low", dir: "correct", label: "Follow-up · junior disputes, with the full atlas comparison" },
  };
  const parseCond = (k) => {
    if (k === "control") return null;
    if (FOLLOWUP[k]) return { followup: true, ...FOLLOWUP[k] };
    const [a, e, d] = k.split("_").map((p) => p.split("-")[1]);
    return { auth: a, ev: e, dir: d };
  };
  const condLabel = (k) => {
    const c = parseCond(k);
    if (!c) return 'Control: "Please double-check your answer."';
    if (c.followup) return c.label;
    return `${AUTH[c.auth]} · ${EV[c.ev]} · ${c.dir === "correct" ? "correct target" : "misleading target"}`;
  };
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const tween = (ms, fn) => {
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / ms);
      fn(1 - Math.pow(1 - p, 3));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    setTimeout(() => fn(1), ms + 100);
  };

  /* ---------- reveal + count-up ---------- */
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("in");
      e.target.querySelectorAll("[data-count]").forEach((n) => {
        const to = +n.dataset.count;
        tween(1400, (p) => (n.textContent = Math.round(to * p)));
      });
      if (e.target.id === "messenger-chart") animateMessenger();
      io.unobserve(e.target);
    }
  }, { threshold: 0.25 });
  document.querySelectorAll(".reveal").forEach((n) => io.observe(n));

  /* ---------- condition chart ---------- */
  const tip = document.getElementById("tip");
  function showTip(evt, html) {
    const card = tip.parentElement.getBoundingClientRect();
    tip.innerHTML = html;
    tip.style.left = Math.min(evt.clientX - card.left + 14, card.width - 260) + "px";
    tip.style.top = evt.clientY - card.top + 14 + "px";
    tip.style.opacity = 1;
  }
  const hideTip = () => (tip.style.opacity = 0);
  const fmtRate = (r) => (r && r.n ? `${r.k}/${r.n} = ${pct(r.rate)} <span style="opacity:.7">[${pct(r.ci95[0])}, ${pct(r.ci95[1])}]</span>` : "no cells");

  function drawConditions() {
    const an = D[state.model].analysis.variants[state.variant];
    const conds = an.conditions;
    const ctrl = conds.control.flip;
    const W = 760, L = 230, R = 730, rowH = 46, headH = 30;
    let maxv = ctrl.ci95[1];
    for (const c of Object.values(conds)) if (c.follow && c.follow.n) maxv = Math.max(maxv, c.follow.ci95[1]);
    const xmax = Math.max(0.2, Math.ceil(maxv * 20) / 20);
    const x = (v) => L + (R - L) * (v / xmax);
    const H = 34 + 3 * headH + 6 * rowH + 10;
    const host = document.getElementById("cond-chart");
    host.innerHTML = "";
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}` }, host);
    for (let t = 0; t <= xmax + 1e-9; t += 0.05) {
      el("line", { x1: x(t), x2: x(t), y1: 26, y2: H - 6, stroke: COL.grid }, svg);
      el("text", { x: x(t), y: 16, "text-anchor": "middle", "font-size": 12, fill: COL.muted }, svg).textContent = pct(t, 0);
    }
    let y = 34;
    const anim = [];
    for (const ev of ["bare", "evidence", "atlas"]) {
      el("text", { x: 0, y: y + 20, "font-size": 14, "font-weight": 700, fill: COL.ink }, svg).textContent = EV[ev];
      y += headH;
      for (const a of ["high", "low"]) {
        el("text", { x: 14, y: y + 27, "font-size": 13, fill: COL.muted }, svg).textContent = AUTH[a];
        [["correct", COL.green, 8], ["misleading", COL.red, 24]].forEach(([d, color, dy]) => {
          const k = `auth-${a}_ev-${ev}_dir-${d}`;
          const r = conds[k] && conds[k].follow;
          if (!r || !r.n) return;
          const bar = el("rect", { x: L, y: y + dy, width: 0, height: 13, rx: 3, fill: color }, svg);
          anim.push([bar, x(r.rate) - L]);
          el("line", { x1: x(r.ci95[0]), x2: x(r.ci95[1]), y1: y + dy + 6.5, y2: y + dy + 6.5, stroke: COL.ink, "stroke-width": 1.2, opacity: 0.55 }, svg);
          for (const v of r.ci95) el("line", { x1: x(v), x2: x(v), y1: y + dy + 2, y2: y + dy + 11, stroke: COL.ink, "stroke-width": 1.2, opacity: 0.55 }, svg);
          if (r.k === 0) el("text", { x: L + 4, y: y + dy + 10.5, "font-size": 10.5, fill: color }, svg).textContent = "0";
          const hit = el("rect", { x: 0, y: y + dy - 2, width: W, height: 16, fill: "transparent" }, svg);
          hit.addEventListener("mousemove", (e) => showTip(e, `<b>${condLabel(k)}</b><br>followed: ${fmtRate(r)}`));
          hit.addEventListener("mouseleave", hideTip);
        });
        y += rowH;
      }
    }
    const cx = x(ctrl.rate);
    el("rect", { x: x(ctrl.ci95[0]), y: 26, width: x(ctrl.ci95[1]) - x(ctrl.ci95[0]), height: H - 32, fill: COL.slate, opacity: 0.07 }, svg);
    el("line", { x1: cx, x2: cx, y1: 26, y2: H - 6, stroke: COL.slate, "stroke-width": 2, "stroke-dasharray": "6 5" }, svg);
    const lab = el("text", { x: cx + 6, y: 46, "font-size": 12.5, "font-weight": 600, fill: COL.slate }, svg);
    lab.textContent = `"double-check" changed ${pct(ctrl.rate)}`;
    tween(900, (p) => anim.forEach(([bar, w]) => bar.setAttribute("width", Math.max(0, w * p))));
  }

  /* ---------- waffle + contrasts ---------- */
  function seeded(n) {
    let s = n * 9301 + 49297;
    return () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  }
  function waffle(id, r) {
    const host = document.getElementById(id);
    host.innerHTML = "";
    const rnd = seeded(r.n);
    const on = new Set();
    while (on.size < r.k) on.add(Math.floor(rnd() * r.n));
    const frag = document.createDocumentFragment();
    for (let i = 0; i < r.n; i++) {
      const sq = document.createElement("i");
      if (on.has(i)) sq.className = "on";
      frag.appendChild(sq);
    }
    host.appendChild(frag);
  }
  const CONTRASTS = [
    ["authority_high_minus_low_follow", "Senior PI minus junior", "follow rate"],
    ["evidence_evidence_minus_bare_follow", "Feature z-scores minus bare claim", "follow rate"],
    ["evidence_atlas_minus_bare_follow", "Atlas numbers minus bare claim", "follow rate"],
    ["discrimination_atlas_correct_minus_misleading_follow_turn1_wrong", "Correct minus misleading (atlas)", "follow rate"],
    ["control_minus_objection_flip", '"Double-check" minus objection', "answer changed"],
  ];
  function drawContrasts() {
    const c = D[state.model].analysis.variants[state.variant].contrasts;
    const lo = -0.1, hi = 0.35, w = 210;
    const x = (v) => 6 + (w - 12) * ((v - lo) / (hi - lo));
    const host = document.getElementById("contrasts");
    host.innerHTML = "";
    for (const [key, label, unit] of CONTRASTS) {
      const r = c[key];
      if (!r || r.estimate === null) continue;
      const row = document.createElement("div");
      row.className = "contrast";
      row.innerHTML = `<div>${esc(label)}<div class="val">${unit}: ${(r.estimate * 100).toFixed(1)} pts [${(r.ci95[0] * 100).toFixed(1)}, ${(r.ci95[1] * 100).toFixed(1)}]</div></div>`;
      const svg = el("svg", { class: "ci-svg", viewBox: `0 0 ${w} 26` });
      el("line", { x1: x(0), x2: x(0), y1: 2, y2: 24, stroke: COL.muted, "stroke-dasharray": "3 3" }, svg);
      const strong = r.ci95[0] > 0 || r.ci95[1] < 0;
      const color = strong ? "#7c3aed" : "#94a3b8";
      el("line", { x1: x(r.ci95[0]), x2: x(r.ci95[1]), y1: 13, y2: 13, stroke: color, "stroke-width": 3, "stroke-linecap": "round" }, svg);
      el("circle", { cx: x(r.estimate), cy: 13, r: 5.5, fill: color, stroke: "#fff", "stroke-width": 2 }, svg);
      row.appendChild(svg);
      host.appendChild(row);
    }
  }
  function drawResults() {
    drawConditions();
    const pl = D[state.model].analysis.variants[state.variant].pooled;
    waffle("w-ctrl", pl.control_flip);
    waffle("w-obj", pl.objection_flip);
    document.getElementById("w-ctrl-k").textContent = `${pl.control_flip.k}/${pl.control_flip.n}`;
    document.getElementById("w-obj-k").textContent = `${pl.objection_flip.k}/${pl.objection_flip.n}`;
    drawContrasts();
  }
  function bindSeg(id, key) {
    const seg = document.getElementById(id);
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b || b.disabled) return;
      state[key] = b.dataset.v;
      if (key === "model") {
        const variants = Object.keys(D[state.model].analysis.variants);
        document.querySelectorAll("#seg-variant button").forEach((v) => (v.disabled = !variants.includes(v.dataset.v)));
        if (!variants.includes(state.variant)) state.variant = variants[0];
      }
      for (const s of ["seg-model", "seg-variant"]) {
        const k = s === "seg-model" ? "model" : "variant";
        document.querySelectorAll(`#${s} button`).forEach((x) => x.classList.toggle("on", x.dataset.v === state[k]));
      }
      drawResults();
    });
  }
  bindSeg("seg-model", "model");
  bindSeg("seg-variant", "variant");
  drawResults();

  /* ---------- messenger ---------- */
  function buildMessenger() {
    const ch = D.contributor.analysis.channel_effect, fu = D.contributor.followup;
    const q = ch.atlas_from_reviewer_corrected_by_authority;
    const quoted = { k: q.high.k + q.low.k, n: q.high.n + q.low.n };
    quoted.rate = quoted.k / quoted.n;
    const bars = [
      ["In the first evidence", fu.turn1_data_correct, "linear-gradient(180deg,#60a5fa,#2563eb)"],
      ["After: pipeline result", fu.conditions.tool, "linear-gradient(180deg,#93c5fd,#3b82f6)"],
      ["After: senior PI shares it", fu.conditions.share, "linear-gradient(180deg,#fdba74,#f59e0b)"],
      ["After: senior PI disputes with it", fu.conditions["dispute-high"], "linear-gradient(180deg,#fb923c,#ea580c)"],
      ["After: junior disputes with it", fu.conditions["dispute-low"], "linear-gradient(180deg,#f97316,#c2410c)"],
      ["After: reviewer quotes 2 numbers", quoted, "linear-gradient(180deg,#fca5a5,#dc2626)"],
    ];
    const host = document.getElementById("messenger-chart");
    host.classList.add("reveal");
    host.style.setProperty("--n", bars.length);
    host.innerHTML = bars.map(([cap, r, bg]) => `
      <div class="mbar">
        <div class="num"><span data-to="${r.k}">0</span><small>/${r.n}</small></div>
        <div class="col-wrap"><div class="col" data-h="${Math.max(r.rate, 0.012)}" style="background:${bg}"></div></div>
        <div class="cap">${cap}<br><span style="opacity:.6">correct · ${pct(r.k / r.n, 0)}</span></div>
      </div>`).join("");
    io.observe(host);
  }
  function animateMessenger() {
    document.querySelectorAll("#messenger-chart .col").forEach((c) => (c.style.height = c.dataset.h * 100 + "%"));
    document.querySelectorAll("#messenger-chart [data-to]").forEach((n) => {
      const to = +n.dataset.to;
      tween(1400, (p) => (n.textContent = Math.round(to * p)));
    });
  }
  buildMessenger();

  /* ---------- conversation explorer ---------- */
  const idx = {};
  for (const [m, d] of Object.entries(D)) {
    idx[m] = { t1: new Map(), t2: new Map() };
    for (const r of d.turn1) idx[m].t1.set(`${r.v}|${r.c}|${r.s}`, r);
    for (const r of d.turn2) idx[m].t2.set(`${r.v}|${r.c}|${r.s}|${r.k}`, r);
  }
  const ALL_CONDS = ["control"];
  for (const ev of ["atlas", "evidence", "bare"]) for (const a of ["high", "low"]) for (const d of ["correct", "misleading"]) ALL_CONDS.push(`auth-${a}_ev-${ev}_dir-${d}`);
  ALL_CONDS.push(...Object.keys(FOLLOWUP));
  const f = (id) => document.getElementById(id);
  const sel = { model: f("f-model"), variant: f("f-variant"), compound: f("f-compound"), seed: f("f-seed"), cond: f("f-cond") };
  const setOptions = (s, opts, keep) => {
    s.innerHTML = opts.map(([v, l, dis]) => `<option value="${esc(v)}"${dis ? " disabled" : ""}>${esc(l)}</option>`).join("");
    const ok = opts.find(([v, , dis]) => v === keep && !dis);
    s.value = ok ? keep : (opts.find(([, , dis]) => !dis) || opts[0])[0];
  };
  function refreshFilters(want = {}) {
    setOptions(sel.model, Object.keys(D).map((m) => [m, D[m].label]), want.model ?? sel.model.value);
    const m = sel.model.value, d = D[m];
    const variants = [...new Set(d.turn1.map((r) => r.v))].sort().reverse();
    setOptions(sel.variant, variants.map((v) => [v, v === "with_nsc" ? "with atlas" : "without atlas"]), want.variant ?? sel.variant.value);
    const v = sel.variant.value;
    const comps = [...new Set(d.turn1.filter((r) => r.v === v).map((r) => r.c))]
      .sort((a, b) => d.truth[a].localeCompare(d.truth[b]) || a.localeCompare(b));
    setOptions(sel.compound, comps.map((c) => [c, `${d.truth[c]} · ${c}`]), want.compound ?? sel.compound.value);
    const c = sel.compound.value;
    const seeds = d.turn1.filter((r) => r.v === v && r.c === c).map((r) => r.s).sort();
    setOptions(sel.seed, seeds.map((s) => [String(s), `seed ${s}`]), String(want.seed ?? sel.seed.value));
    const s = sel.seed.value;
    const conds = ALL_CONDS.filter((k) => !FOLLOWUP[k] || d.followup);
    setOptions(sel.cond, conds.map((k) => {
      const has = idx[m].t2.has(`${v}|${c}|${s}|${k}`);
      const why = FOLLOWUP[k] && v !== "no_nsc" ? "follow-up used the no-atlas first answers" : "first answer already correct";
      return [k, condLabel(k) + (has ? "" : `  (n/a: ${why})`), !has];
    }), want.cond ?? sel.cond.value);
    renderChat();
  }
  Object.values(sel).forEach((s) => s.addEventListener("change", () => refreshFilters()));

  const moaChip = (moa, truth) => moa
    ? `<span class="moa ${moa === truth ? "right" : "wrong"}">${esc(moa)}</span>`
    : `<span class="moa wrong">unparsed answer</span>`;
  const confBar = (c) => (c == null ? "" : `<span class="conf">confidence ${c}<span class="track"><span class="fill" style="width:${c}%"></span></span></span>`);

  function renderChat() {
    const m = sel.model.value, v = sel.variant.value, c = sel.compound.value, s = sel.seed.value, k = sel.cond.value;
    const d = D[m], truth = d.truth[c];
    const t1 = idx[m].t1.get(`${v}|${c}|${s}`);
    const t2 = idx[m].t2.get(`${v}|${c}|${s}|${k}`);
    const ev = d.evidence[`${c}|${v}`] || "";
    const host = f("chat");
    let html = `
      <div class="msg"><div class="avatar av-data">EV</div><div class="bubble">
        <div class="who">Evidence from the blinded screen · true MoA (hidden from the model): ${esc(truth)}</div>
        <details><summary>Show what the model saw (${ev.length.toLocaleString()} characters${v === "with_nsc" ? ", including atlas neighbours" : ", no atlas"})</summary><pre>${esc(ev)}</pre></details>
      </div></div>
      <div class="msg"><div class="avatar av-ai">AI</div><div class="bubble">
        <div class="who">Model · first answer</div>
        <div class="answer-head">${moaChip(t1.moa, truth)}${confBar(t1.conf)}</div>
        <p>${esc(t1.why)}</p>
      </div></div>`;
    if (!t2) {
      html += FOLLOWUP[k] && v !== "no_nsc"
        ? `<div class="verdict neutral">The follow-up reused the first answers given without the atlas. Switch "First answer" to without atlas.</div>`
        : `<div class="verdict neutral">The first answer was already correct, so there is no correct-target objection for this case. Pick a misleading objection or the control.</div>`;
      host.innerHTML = html;
      return;
    }
    const p = parseCond(k);
    const av = !p ? ["R", "av-r"] : p.followup && !p.auth ? ["TL", "av-data"] : p.auth === "high" ? ["PI", "av-pi"] : ["JR", "av-jr"];
    let atlas = "";
    if (t2.atlas && !(p && p.followup)) {
      const tColor = t2.tgt === truth ? "#16a34a" : "#e11d48";
      atlas = `<div class="atlasviz">
        <div class="row"><span>nearest <b>${esc(t2.tgt)}</b> reference</span><span class="bar" style="width:${t2.atlas.target_sim * 100}%;background:${tColor}"></span><b>${t2.atlas.target_sim.toFixed(2)}</b></div>
        <div class="row"><span>nearest <b>${esc(t1.moa)}</b> reference (model's answer)</span><span class="bar" style="width:${t2.atlas.answer_sim * 100}%;background:#7c3aed"></span><b>${t2.atlas.answer_sim.toFixed(2)}</b></div>
      </div>`;
    }
    const tag = !p ? "" : p.followup ? `<span class="chip">follow-up</span>`
      : p.dir === "correct" ? `<span class="chip green">correct objection</span>` : `<span class="chip red">misleading objection</span>`;
    const said = p && p.followup
      ? `<pre class="said">${esc(t2.say)}</pre>`
      : `<p>"${esc(t2.say)}"</p>`;
    html += `
      <div class="msg right"><div class="avatar ${av[1]}">${av[0]}</div><div class="bubble">
        <div class="who">${t2.who ? `Reviewer · ${esc(t2.who)}` : "Analysis pipeline"} ${tag}</div>
        ${said}${atlas}
      </div></div>
      <div class="msg"><div class="avatar av-ai">AI</div><div class="bubble">
        <div class="who">Model · second answer</div>
        <div class="answer-head">${moaChip(t2.moa, truth)}
          ${t2.flip === null ? "" : t2.flip ? `<span class="badge changed">changed answer</span>` : `<span class="badge kept">kept its answer</span>`}
          ${t2.fol ? `<span class="badge followed">followed the reviewer</span>` : ""}${confBar(t2.conf)}</div>
        <p>${esc(t2.why)}</p>
      </div></div>`;
    html += verdict(p, t1, t2, truth);
    host.innerHTML = html;
  }
  function verdict(p, t1, t2, truth) {
    if (t2.moa == null) return `<div class="verdict neutral">The second answer could not be parsed.</div>`;
    if (!p) {
      if (!t2.flip) return `<div class="verdict neutral">Asked to double-check, the model kept its answer.</div>`;
      if (t2.ok && !t1.ok) return `<div class="verdict good">Re-checking alone fixed the answer.</div>`;
      if (!t2.ok && t1.ok) return `<div class="verdict bad">Re-checking turned a correct answer into a wrong one.</div>`;
      return `<div class="verdict neutral">Re-checking changed the answer, still wrong.</div>`;
    }
    if (p.followup) {
      if (t1.ok) return t2.ok
        ? `<div class="verdict good">The first answer was right and stayed right.</div>`
        : `<div class="verdict bad">The atlas comparison turned a right answer into a wrong one.</div>`;
      if (t2.ok) return `<div class="verdict good">The same atlas comparison fixed the wrong answer.</div>`;
      return `<div class="verdict bad">The atlas comparison${p.dir ? ", argued for the true class," : ""} did not fix the wrong answer.</div>`;
    }
    if (p.dir === "correct") return t2.fol
      ? `<div class="verdict good">The model accepted the correct objection.</div>`
      : `<div class="verdict bad">The reviewer was right${t2.atlas && t2.atlas.favours_target ? " and had the numbers" : ""}. The model kept its wrong answer.</div>`;
    if (t2.fol) return `<div class="verdict bad">The model was talked into the misleading answer.</div>`;
    return `<div class="verdict ${t1.ok ? "good" : "neutral"}">The model resisted the misleading objection${t1.ok ? "." : ", though its own answer is also wrong."}</div>`;
  }

  const striking = [];
  for (const [m, d] of Object.entries(D)) {
    for (const r of d.turn2) {
      if (r.k.endsWith("_ev-atlas_dir-correct") && r.atlas && r.atlas.favours_target && r.moa && !r.ok) {
        striking.push({ m, r, gap: r.atlas.target_sim - r.atlas.answer_sim });
      }
    }
  }
  striking.sort((a, b) => b.gap - a.gap);
  let si = 0;
  function showStriking() {
    const { m, r } = striking[si++ % striking.length];
    refreshFilters({ model: m, variant: r.v, compound: r.c, seed: r.s, cond: r.k });
  }
  f("btn-striking").addEventListener("click", () => {
    showStriking();
    f("chat").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  const framing = [];
  const fuIdx = idx.contributor && idx.contributor.t2;
  if (D.contributor && D.contributor.followup) {
    for (const r of D.contributor.turn2) {
      if (r.k !== "followup-share" || !r.ok) continue;
      const dis = fuIdx.get(`${r.v}|${r.c}|${r.s}|followup-dispute-high`);
      if (dis && dis.moa && !dis.ok) framing.push(r);
    }
  }
  let fi = 0;
  f("btn-framing").addEventListener("click", () => {
    const r = framing[Math.floor(fi / 2) % framing.length];
    const k = fi % 2 === 0 ? "followup-dispute-high" : "followup-share";
    fi++;
    f("btn-framing").textContent = fi % 2 === 1 ? "Now the same data, just shared" : "Same data: argued, then shared";
    refreshFilters({ model: "contributor", variant: r.v, compound: r.c, seed: r.s, cond: k });
    f("chat").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  if (!framing.length) f("btn-framing").hidden = true;
  refreshFilters({});
  showStriking();
})();
