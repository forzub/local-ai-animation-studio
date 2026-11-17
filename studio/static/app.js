"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  models: [], roles: {}, aspects: [],
  kind: "image", mode: null, model: null,
  refs: [],            // {upload_id, role, url}
  aspect: "1:1", count: 1,
  jobs: new Map(), favOnly: false,
  video: {},           // выбранные параметры видео
};
const MODE_HINT_ROLE = { edit: "base", i2i: "base", i2v: "start" };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/* ---------- композер ---------- */
function modelsOfKind() { return S.models.filter((m) => m.kind === S.kind); }
function currentModel() { return S.models.find((m) => m.id === S.model); }

function setKind(kind) {
  S.kind = kind;
  document.querySelectorAll("#kindTabs button").forEach((b) => b.classList.toggle("active", b.dataset.kind === kind));
  const list = modelsOfKind();
  const sel = $("#model");
  sel.innerHTML = list.map((m) => `<option value="${m.id}" ${m.missing.length ? "disabled" : ""}>${esc(m.name)}${m.missing.length ? " — нет файлов" : ""}</option>`).join("")
    || `<option value="">Нет подключённых моделей</option>`;
  const first = list.find((m) => !m.missing.length);
  setModel(first ? first.id : null);
}

function setModel(id) {
  S.model = id;
  $("#model").value = id || "";
  const m = currentModel();
  $("#modelDesc").textContent = m ? `${m.description} Лицензия: ${m.license}.` : "";
  const lim = $("#modelLimits");
  lim.hidden = !m || !m.limits.length;
  if (m) lim.querySelector("ul").innerHTML = m.limits.map((l) => `<li>${esc(l)}</li>`).join("");
  const modes = m ? Object.entries(m.modes) : [];
  $("#modeSeg").innerHTML = modes.map(([k, v]) => `<button type="button" data-mode="${k}">${esc(v)}</button>`).join("");
  setMode(modes.some(([k]) => k === S.mode) ? S.mode : modes[0]?.[0]);
  if (m?.defaults?.strength) $("#strength").value = m.defaults.strength;
  renderVideoOpts();
  $("#go").disabled = !m;
}

function setMode(mode) {
  S.mode = mode;
  document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  const m = currentModel();
  $("#refsSection").hidden = !m || m.max_refs === 0;
  $("#aspectRow").hidden = mode === "edit" || mode === "i2i" || mode === "i2v";
  $("#strengthRow").hidden = mode !== "i2i";
  $("#imageOpts").hidden = S.kind !== "image";
  $("#videoOpts").hidden = S.kind !== "video";
  $("#negativeRow").hidden = S.kind !== "video";
  // назначить исходник, если режим его требует
  const need = MODE_HINT_ROLE[mode];
  if (need && S.refs.length && !S.refs.some((r) => r.role === need) && m?.ref_roles.includes(need)) S.refs[0].role = need;
  fixRoles();
  renderRefs();
  renderVideoOpts();
}

function fixRoles() {
  const m = currentModel();
  if (!m) return;
  for (const r of S.refs) if (!m.ref_roles.includes(r.role)) r.role = m.ref_roles.find((x) => x !== "base") || m.ref_roles[0];
}

function renderRefs() {
  const m = currentModel();
  const roles = m ? m.ref_roles : [];
  $("#refCount").textContent = m && m.max_refs ? `${S.refs.length} / ${m.max_refs}` : "";
  $("#refs").innerHTML = S.refs.map((r, i) => `
    <div class="ref">
      <img src="${r.url}" alt="референс ${i + 1}">
      <span class="num">${i + 1}</span>
      <button type="button" class="rm" data-i="${i}" title="Убрать">×</button>
      <select data-i="${i}">${roles.map((k) => `<option value="${k}" ${k === r.role ? "selected" : ""}>${esc(S.roles[k] || k)}</option>`).join("")}</select>
    </div>`).join("");
  $("#drop").hidden = m && S.refs.length >= m.max_refs;
}

function defaultRole() {
  const m = currentModel();
  const need = MODE_HINT_ROLE[S.mode];
  if (need && m?.ref_roles.includes(need) && !S.refs.some((r) => r.role === need)) return need;
  if (m?.ref_roles.includes("character") && !S.refs.some((r) => r.role === "character")) return "character";
  return m?.ref_roles.find((x) => x !== "base" && x !== "start" && x !== "end") || "character";
}

async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    const m = currentModel();
    if (m && S.refs.length >= m.max_refs) { showError(`Модель принимает не более ${m.max_refs} референсов`); break; }
    const fd = new FormData();
    fd.append("file", f);
    try {
      const u = await api("/api/uploads", { method: "POST", body: fd });
      S.refs.push({ upload_id: u.upload_id, url: u.url, role: defaultRole() });
      renderRefs();
    } catch (e) { showError(e.message); }
  }
}

function addRefFromUpload(u, role) {
  const m = currentModel();
  if (S.refs.some((r) => r.upload_id === u.upload_id)) return;
  if (m && S.refs.length >= m.max_refs) S.refs.pop();
  S.refs.push({ upload_id: u.upload_id, url: u.url, role: role || defaultRole() });
  renderRefs();
}

function renderVideoOpts() {
  const m = currentModel();
  const box = $("#videoOpts");
  const vo = m && m.video_options;
  if (!vo) { box.innerHTML = S.kind === "video" ? `<p class="hint">Видеомодель ещё не подключена.</p>` : ""; return; }
  const sel = S.video;
  sel.duration ??= vo.default_duration; sel.resolution ??= vo.default_resolution; sel.camera ??= "";
  box.innerHTML = `
    <div class="row"><label class="lbl">Длительность</label><div class="chips" id="durations">
      ${vo.durations.map((d) => `<button type="button" data-v="${d}" class="${d == sel.duration ? "active" : ""}">${d} с</button>`).join("")}</div></div>
    <div class="row"><label class="lbl" for="vres">Разрешение</label><select id="vres">
      ${Object.entries(vo.resolutions).map(([k, v]) => `<option value="${k}" ${k === sel.resolution ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
    <div class="row" id="vAspectRow"><label class="lbl">Формат</label><div class="chips" id="vaspects">
      ${vo.aspects.map((a) => `<button type="button" data-v="${a}" class="${a === S.aspect ? "active" : ""}">${a}</button>`).join("")}</div></div>
    <div class="row"><label class="lbl" for="vcam">Камера</label><select id="vcam">
      ${Object.entries(vo.cameras).map(([k, v]) => `<option value="${k}" ${k === sel.camera ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
    ${vo.time_note ? `<p class="hint">${esc(vo.time_note)}</p>` : ""}`;
  if (!vo.aspects.includes(S.aspect)) S.aspect = vo.aspects[0];
  $("#vAspectRow").hidden = S.mode === "i2v";
  box.querySelectorAll("#vaspects button").forEach((b) => b.classList.toggle("active", b.dataset.v === S.aspect));
}

function renderChips() {
  $("#aspects").innerHTML = S.aspects.map((a) => `<button type="button" data-v="${a}" class="${a === S.aspect ? "active" : ""}">${a}</button>`).join("");
  $("#counts").innerHTML = [1, 2, 3, 4].map((n) => `<button type="button" data-v="${n}" class="${n === S.count ? "active" : ""}">${n}</button>`).join("");
}

function showError(msg) { const e = $("#formError"); e.textContent = msg; e.hidden = !msg; }

function collectParams() {
  const num = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };
  const p = {
    model: S.model, mode: S.mode, prompt: $("#prompt").value.trim(),
    refs: S.refs.map((r) => ({ upload_id: r.upload_id, role: r.role })),
    aspect: S.aspect, megapixels: Number($("#quality").value), count: S.count,
    seed: num("#seed"), steps: num("#steps"), ref_megapixels: num("#refMp"),
    strength: S.mode === "i2i" ? Number($("#strength").value) : null,
    role_prompts: $("#rolePrompts").checked,
  };
  if (S.kind === "video") {
    p.duration = Number(S.video.duration); p.resolution = S.video.resolution; p.camera = S.video.camera || null;
    p.count = 1;
    p.negative = $("#negative").value.trim() || null;
  }
  return p;
}

async function submit(ev) {
  ev?.preventDefault();
  showError("");
  const p = collectParams();
  if (!p.prompt && !p.refs.length) { showError("Введите промпт или прикрепите референс"); return; }
  $("#go").disabled = true;
  try {
    await api("/api/jobs", { method: "POST", body: JSON.stringify(p) });
    await refreshJobs();
    $("#jobs").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { showError(e.message); }
  finally { $("#go").disabled = false; }
}

/* повторить задачу: загрузить её параметры в композер */
function loadParams(job, keepSeed) {
  const p = job.params;
  const m = S.models.find((x) => x.id === p.model);
  if (!m) { showError("Модель этой задачи больше не подключена"); return; }
  setKind(m.kind);
  setModel(m.id);
  setMode(p.mode);
  $("#prompt").value = p.prompt || "";
  S.refs = (p.refs || []).map((r) => ({ ...r, url: `/uploads/${r.upload_id}` }));
  S.aspect = p.aspect || "1:1"; S.count = p.count || 1;
  $("#quality").value = String(p.megapixels ?? 1);
  $("#seed").value = keepSeed ? p.seed : "";
  $("#steps").value = p.steps ?? "";
  $("#refMp").value = p.ref_megapixels ?? "";
  $("#rolePrompts").checked = p.role_prompts !== false;
  if (p.strength) $("#strength").value = p.strength;
  if (m.kind === "video") S.video = { duration: p.duration, resolution: p.resolution, camera: p.camera || "" };
  $("#negative").value = p.negative || "";
  renderChips(); renderRefs(); renderVideoOpts(); updateStrength();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function useOutput(job, out, action) {
  const frame = out.media === "video" ? "last" : null;
  const u = await api("/api/uploads/from-output", { method: "POST", body: JSON.stringify({ job_id: job.id, file: out.file, frame }) });
  if (action === "ref") { addRefFromUpload(u); return; }
  if (action === "edit") {
    setKind("image"); setMode("edit");
    S.refs = S.refs.filter((r) => r.role !== "base");
    S.refs.unshift({ upload_id: u.upload_id, url: u.url, role: "base" });
    renderRefs();
  }
  if (action === "animate") {
    setKind("video");
    if (!currentModel()) { showError("Видеомодель ещё не подключена"); return; }
    setMode("i2v");
    S.refs = [{ upload_id: u.upload_id, url: u.url, role: "start" }];
    renderRefs();
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
  $("#prompt").focus();
}

/* ---------- лента задач ---------- */
const STATUS = { queued: "в очереди", running: "выполняется", done: "готово", failed: "ошибка", cancelled: "отменено" };
const fmtTime = (t) => new Date(t * 1000).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dur = (j) => j.started && j.finished ? ` · ${Math.round(j.finished - j.started)} с` : "";

function jobSignature(j) { return [j.status, j.outputs.length, j.favorite, j.error].join("|"); }

function jobHTML(j) {
  const m = S.models.find((x) => x.id === j.model);
  const modeName = m?.modes[j.mode] || j.mode;
  const active = j.status === "queued" || j.status === "running";
  const p = j.params;
  return `
    <div class="job-head">
      <span class="badge ${j.status}">${STATUS[j.status]}</span>
      <span>${esc(modeName)} · ${esc(m?.name || j.model)}</span>
      <span>${fmtTime(j.created)}${dur(j)}</span>
      <span>seed ${p.seed}</span>
      <span class="spacer"></span>
      <div class="job-actions">
        ${active ? `<button class="btn" data-act="cancel">Отменить</button>` : `
        <button class="btn" data-act="repeat" title="Загрузить параметры с тем же seed">Повторить</button>
        <button class="btn" data-act="vary" title="Те же параметры, новый seed">Новый seed</button>
        <button class="btn ${j.favorite ? "fav-on" : ""}" data-act="fav" title="Избранное">★</button>
        <button class="btn" data-act="del" title="Удалить из истории вместе с файлами">Удалить</button>`}
      </div>
    </div>
    ${p.prompt ? `<div class="job-prompt">${esc(p.prompt)}</div>` : ""}
    ${p.refs?.length ? `<div class="job-refs">${p.refs.map((r, i) => `<img src="/uploads/${r.upload_id}" title="${i + 1}: ${esc(S.roles[r.role] || r.role)}" alt="">`).join("")}</div>` : ""}
    ${active ? `<div class="progress"><div style="width:${Math.round((j.progress || 0) * 100)}%"></div></div><div class="stage">${esc(j.stage || (j.status === "queued" ? "Ожидает очереди" : ""))}</div>` : ""}
    ${j.error ? `<div class="job-error">${esc(j.error)}</div>` : ""}
    ${j.outputs.length ? `<div class="outs">${j.outputs.map((o, i) => outHTML(j, o, i)).join("")}</div>` : ""}`;
}

function outHTML(j, o, i) {
  const url = `/files/${j.id}/${o.file}`;
  const media = o.media === "video"
    ? `<video src="${url}" data-lb="${i}" muted loop playsinline preload="metadata" onmouseenter="this.play()" onmouseleave="this.pause()"></video>`
    : `<img src="${url}" data-lb="${i}" loading="lazy" alt="результат ${i + 1}">`;
  const tag = o.role === "keyframe" ? `<span class="tag">ключевой кадр</span>` : "";
  return `<div class="out">${media}${tag}<div class="bar">
      <a class="btn" href="${url}?download=true">Скачать</a>
      ${o.media === "video" ? `<button class="btn" data-out="${i}" data-use="animate" title="Последний кадр станет началом нового видео">Продолжить с последнего кадра</button>
      <button class="btn" data-out="${i}" data-use="ref">Последний кадр в референсы</button>` : `<button class="btn" data-out="${i}" data-use="ref">В референсы</button>
      <button class="btn" data-out="${i}" data-use="edit">Редактировать</button>
      <button class="btn" data-out="${i}" data-use="animate">Анимировать</button>`}
    </div></div>`;
}

function renderJobs(list) {
  const box = $("#jobs");
  const ids = new Set(list.map((j) => j.id));
  for (const el of [...box.children]) if (!ids.has(el.dataset.id)) el.remove();
  let prev = null;
  for (const j of list) {
    let el = box.querySelector(`[data-id="${j.id}"]`);
    const sig = jobSignature(j);
    if (!el) {
      el = document.createElement("article");
      el.className = "job"; el.dataset.id = j.id;
      el.innerHTML = jobHTML(j); el.dataset.sig = sig;
    } else if (el.dataset.sig !== sig) {
      el.innerHTML = jobHTML(j); el.dataset.sig = sig;
    } else if (j.status === "running") {
      const bar = el.querySelector(".progress > div");
      if (bar) bar.style.width = `${Math.round((j.progress || 0) * 100)}%`;
      const st = el.querySelector(".stage");
      if (st) st.textContent = j.stage || "";
    }
    if (prev ? prev.nextSibling !== el : box.firstChild !== el) prev ? prev.after(el) : box.prepend(el);
    prev = el;
    S.jobs.set(j.id, j);
  }
  $("#empty").hidden = list.length > 0;
}

let pollTimer = null;
async function refreshJobs() {
  clearTimeout(pollTimer);
  let active = false;
  try {
    const { jobs } = await api(`/api/jobs?limit=60${S.favOnly ? "&favorites=true" : ""}`);
    renderJobs(jobs);
    active = jobs.some((j) => j.status === "queued" || j.status === "running");
  } catch {}
  pollTimer = setTimeout(refreshJobs, active ? 1000 : 8000);
}

function showModels() {
  const kinds = { image: "Изображения", video: "Видео" };
  $("#modelsList").innerHTML = S.models.map((m) => `
    <div class="mcard">
      <h3>${esc(m.name)} <span class="muted">· ${kinds[m.kind] || m.kind} · ${esc(m.license)}</span>
        ${m.missing.length ? `<span class="bad-t">нет файлов</span>` : `<span class="ok-t">готова</span>`}</h3>
      <div class="hint">${esc(m.description)}</div>
      <div class="hint">Режимы: ${Object.values(m.modes).map(esc).join(", ")}${m.max_refs ? ` · до ${m.max_refs} референсов` : ""}</div>
      ${m.missing.length ? `<ul>${m.missing.map((f) => `<li>отсутствует <code>${esc(f)}</code></li>`).join("")}</ul>` : ""}
      ${m.limits.length ? `<ul>${m.limits.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
    </div>`).join("");
  $("#modelsDlg").showModal();
}

let statusTimer = null;
async function refreshStatus(once) {
  if (once === true) clearTimeout(statusTimer);
  try {
    const s = await api("/api/status");
    const el = $("#status");
    el.classList.toggle("ok", s.engine === "running");
    const gpu = s.gpu ? `${s.gpu.name} · свободно ${(s.gpu.vram_free / 2 ** 30).toFixed(1)} из ${(s.gpu.vram_total / 2 ** 30).toFixed(1)} ГБ` : "движок запускается…";
    el.innerHTML = `<span class="dot"></span>${esc(gpu)}${s.queued ? ` · в работе: ${s.queued}` : ""}`;
  } catch { $("#status").textContent = "сервер недоступен"; }
  statusTimer = setTimeout(refreshStatus, 5000);
}

/* ---------- лайтбокс ---------- */
let LB = { job: null, i: 0 };
function openLB(job, i) { LB = { job, i }; drawLB(); $("#lightbox").hidden = false; }
function drawLB() {
  const o = LB.job.outputs[LB.i];
  const url = `/files/${LB.job.id}/${o.file}`;
  $("#lbMedia").innerHTML = o.media === "video" ? `<video src="${url}" controls autoplay loop></video>` : `<img src="${url}" alt="">`;
  $("#lbCaption").textContent = `${LB.i + 1} / ${LB.job.outputs.length} · ${o.width}×${o.height} · seed ${o.seed}`;
}
function stepLB(d) { const n = LB.job.outputs.length; LB.i = (LB.i + d + n) % n; drawLB(); }
function closeLB() { $("#lightbox").hidden = true; $("#lbMedia").innerHTML = ""; }

/* ---------- события ---------- */
function bind() {
  $("#kindTabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setKind(b.dataset.kind); });
  $("#model").addEventListener("change", (e) => setModel(e.target.value));
  $("#modeSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); });
  $("#aspects").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.aspect = b.dataset.v; renderChips(); } });
  $("#counts").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.count = Number(b.dataset.v); renderChips(); } });
  $("#videoOpts").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.closest("#durations")) S.video.duration = Number(b.dataset.v);
    if (b.closest("#vaspects")) S.aspect = b.dataset.v;
    renderVideoOpts();
  });
  $("#videoOpts").addEventListener("change", (e) => {
    if (e.target.id === "vres") S.video.resolution = e.target.value;
    if (e.target.id === "vcam") S.video.camera = e.target.value;
  });
  $("#refs").addEventListener("click", (e) => { const b = e.target.closest(".rm"); if (b) { S.refs.splice(Number(b.dataset.i), 1); renderRefs(); } });
  $("#refs").addEventListener("change", (e) => { if (e.target.matches("select")) S.refs[Number(e.target.dataset.i)].role = e.target.value; });
  const drop = $("#drop");
  drop.addEventListener("click", () => $("#fileInput").click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#fileInput").click(); } });
  $("#fileInput").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); });
  document.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  $("#strength").addEventListener("input", updateStrength);
  $("#seedClear").addEventListener("click", () => { $("#seed").value = ""; });
  $("#composer").addEventListener("submit", submit);
  $("#prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(e); });
  $("#favOnly").addEventListener("change", (e) => { S.favOnly = e.target.checked; $("#jobs").innerHTML = ""; refreshJobs(); });

  $("#jobs").addEventListener("click", async (e) => {
    const card = e.target.closest(".job"); if (!card) return;
    const job = S.jobs.get(card.dataset.id);
    const lb = e.target.closest("[data-lb]");
    if (lb) { openLB(job, Number(lb.dataset.lb)); return; }
    const use = e.target.closest("[data-use]");
    if (use) { try { await useOutput(job, job.outputs[Number(use.dataset.out)], use.dataset.use); } catch (err) { showError(err.message); } return; }
    const act = e.target.closest("[data-act]")?.dataset.act;
    try {
      if (act === "cancel") await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      if (act === "repeat") loadParams(job, true);
      if (act === "vary") { await api("/api/jobs", { method: "POST", body: JSON.stringify({ ...job.params, seed: null }) }); }
      if (act === "fav") await api(`/api/jobs/${job.id}/favorite?value=${!job.favorite}`, { method: "POST" });
      if (act === "del") { if (!confirm("Удалить задачу и её файлы с диска?")) return; await api(`/api/jobs/${job.id}`, { method: "DELETE" }); }
      if (act) refreshJobs();
    } catch (err) { alert(err.message); }
  });
  $("#modelsBtn").addEventListener("click", showModels);
  $("#modelsClose").addEventListener("click", () => $("#modelsDlg").close());
  $("#freeBtn").addEventListener("click", async () => {
    const b = $("#freeBtn"); b.disabled = true;
    try { await api("/api/engine/free", { method: "POST" }); } catch (e) { alert(e.message); }
    b.disabled = false; refreshStatus(true);
  });
  $("#lbClose").addEventListener("click", closeLB);
  $("#lbPrev").addEventListener("click", () => stepLB(-1));
  $("#lbNext").addEventListener("click", () => stepLB(1));
  $("#lightbox").addEventListener("click", (e) => { if (e.target.id === "lightbox") closeLB(); });
  document.addEventListener("keydown", (e) => {
    if ($("#lightbox").hidden) return;
    if (e.key === "Escape") closeLB();
    if (e.key === "ArrowLeft") stepLB(-1);
    if (e.key === "ArrowRight") stepLB(1);
  });
}

function updateStrength() { $("#strengthVal").textContent = Math.round(Number($("#strength").value) * 100) + "%"; }

async function init() {
  bind();
  const d = await api("/api/models");
  S.models = d.models; S.roles = d.roles; S.aspects = d.aspects;
  renderChips(); updateStrength();
  setKind("image");
  refreshJobs(); refreshStatus();
}
init();
