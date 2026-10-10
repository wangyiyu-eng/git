// app.js —— DeepSeek-Vision 答卷智能判题系统 前端交互（无登录版）
// 流程：① 上传 → ② 信息 → ③ 判题 → 逐题折叠面板 + 错误统计 + 薄弱知识点 + 导出CSV

const API_BASE = new URLSearchParams(location.search).get("api")
  || (location.hostname === "localhost" || location.hostname === "127.0.0.1"
      ? "http://localhost:8000"
      : `${location.protocol}//${location.hostname}:8000`);

const state = {
  files: [],             // File[]
  confirmed: false,
  currentStep: 1,
  lastResults: null,     // 当前判题结果（用于导出CSV / 切换页面保留）
  currentPage: "judge",  // judge | analytics
};

// ---------- DOM ----------
const $ = (sel) => document.querySelector(sel);
const dropZone = $("#dropZone");
const fileInput = $("#fileInput");
const fileInput2 = $("#fileInput2");
const previewList = $("#previewList");
const confirmCount = $("#confirmCount");
const btnUpload = $("#btnUpload");
const btnJudge = $("#btnJudge");
const btnBatch = $("#btnBatch");
const btnClear = $("#btnClear");
const btnConfirm = $("#btnConfirm");
const btnNext2 = $("#btnNext2");
const btnBack1 = $("#btnBack1");
const btnBack2 = $("#btnBack2");
const progress = $("#progress");
const progressFill = $("#progressFill");
const progressText = $("#progressText");
const resultArea = $("#resultArea");
const apiStatus = $("#apiStatus");
const questionContext = $("#questionContext");
const fullScore = $("#fullScore");
const confirmSummary = $("#confirmSummary");
const toastWrap = $("#toastWrap");
const stepItems = document.querySelectorAll(".step-item");
const stepPanels = {
  1: $("#stepPanel1"), 2: $("#stepPanel2"), 3: $("#stepPanel3"),
};
const topnav = $("#topnav");
const pages = {
  judge: $("#page-judge"),
  analytics: $("#page-analytics"),
};

// ---------- 初始化 ----------
(async function init() {
  await checkHealth();
  bindEvents();
})();

// ---------- API 健康检查 ----------
async function checkHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    const j = await r.json();
    apiStatus.textContent = "● 后端在线";
    apiStatus.classList.add("ok");
  } catch (e) {
    apiStatus.textContent = "● 后端未连接";
    apiStatus.classList.add("fail");
  }
}

// ---------- Toast ----------
function toast(text, type = "info", ms = 2200) {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = text;
  toastWrap.appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 280);
  }, ms);
}

// ---------- 事件 ----------
function bindEvents() {
  dropZone.addEventListener("click", (e) => {
    if (e.target.closest(".preview-list")) return;
    fileInput.click();
  });
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault(); dropZone.classList.add("dragging");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault(); dropZone.classList.remove("dragging");
    addFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener("change", (e) => {
    addFiles(e.target.files); fileInput.value = "";
  });
  btnUpload.addEventListener("click", () => fileInput2.click());
  fileInput2.addEventListener("change", (e) => {
    addFiles(e.target.files); fileInput2.value = "";
  });
  btnClear.addEventListener("click", clearAll);
  btnConfirm.addEventListener("click", onConfirm);
  btnNext2.addEventListener("click", () => gotoStep(3));
  btnBack1.addEventListener("click", () => gotoStep(1));
  btnBack2.addEventListener("click", () => gotoStep(2));
  btnJudge.addEventListener("click", () => doJudge(false));
  btnBatch.addEventListener("click", () => doJudge(true));

  // 顶部导航
  topnav.addEventListener("click", (e) => {
    const t = e.target.closest(".nav-item");
    if (!t) return;
    switchPage(t.dataset.page);
  });

  // 结果筛选
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (!t) return;
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    applyFilter(t.dataset.filter);
  });

  // 导出 CSV
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-action='export-csv']");
    if (!t) return;
    exportCsv(t.dataset.target);
  });

  // 逐题导航：题号 chip / 左右箭头翻页
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".pn-chip");
    const arrow = e.target.closest(".pn-arrow");
    if (!chip && !arrow) return;
    const nav = (chip || arrow).closest(".problem-nav");
    if (!nav || nav.dataset.single) return;
    const pagesWrap = nav.nextElementSibling;
    if (!pagesWrap || !pagesWrap.classList.contains("pn-pages")) return;

    const chips = [...nav.querySelectorAll(".pn-chip")];
    const cur = chips.findIndex(c => c.classList.contains("active"));
    let next = chip ? chips.indexOf(chip) : cur + (+arrow.dataset.dir);
    next = Math.max(0, Math.min(chips.length - 1, next));
    if (next === cur && chip) return;

    chips.forEach((c, i) => c.classList.toggle("active", i === next));
    const targetIdx = +chips[next].dataset.idx;
    pagesWrap.querySelectorAll(".pn-page").forEach(pg => {
      pg.classList.toggle("active", +pg.dataset.idx === targetIdx);
    });
  });
}

// ---------- 页面切换 ----------
function switchPage(name) {
  state.currentPage = name;
  document.querySelectorAll(".nav-item").forEach(n => {
    n.classList.toggle("active", n.dataset.page === name);
  });
  Object.entries(pages).forEach(([k, el]) => {
    el.classList.toggle("active", k === name);
  });
  // 切换 main 布局：判题页=左右两栏；分析页=单列宽幅
  document.querySelector("main").classList.toggle("wide", name === "analytics");

  // 进入学情分析页时：加载数据（仅加载一次，切换周期或刷新时再重载）
  if (name === "analytics") {
    if (!analytics.loaded) loadAnalytics();
    else applyAnalyticsRange();
  }
  // 离开时释放图表实例
  if (name !== "analytics" && analytics.loaded) {
    disposeAnalyticsCharts();
  }
}

// ---------- 文件处理 ----------
function addFiles(fileList) {
  let added = 0;
  for (const f of fileList) {
    if (!f.type.startsWith("image/")) {
      toast(`已忽略非图片文件：${f.name}`, "warn");
      continue;
    }
    if (state.confirmed) { state.confirmed = false; state.lastResults = null; }
    state.files.push(f);
    added++;
  }
  renderPreviews();
  if (added > 0) toast(`已添加 ${added} 张答卷`, "ok");
}

function renderPreviews() {
  previewList.classList.toggle("empty", state.files.length === 0);
  previewList.innerHTML = "";
  if (state.files.length === 0) {
    previewList.innerHTML = `<div class="preview-empty"><span class="empty-icon">📂</span> 尚未选择答卷</div>`;
  } else {
    state.files.forEach((f, idx) => {
      const item = document.createElement("div");
      item.className = "item";
      const url = URL.createObjectURL(f);
      const sizeKb = (f.size / 1024).toFixed(1);
      item.innerHTML = `
        <img src="${url}" alt="" />
        <button class="remove" data-idx="${idx}" title="移除">×</button>
        <div class="name">${f.name}</div>
        <div class="meta">${sizeKb} KB</div>
      `;
      previewList.appendChild(item);
    });
    previewList.querySelectorAll(".remove").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.files.splice(+btn.dataset.idx, 1);
        if (state.confirmed) { state.confirmed = false; state.lastResults = null; }
        renderPreviews();
      });
    });
  }
  confirmCount.textContent = state.files.length;
  btnConfirm.disabled = state.files.length === 0;
  btnClear.disabled = state.files.length === 0;
}

function clearAll() {
  state.files = [];
  state.confirmed = false;
  state.lastResults = null;
  renderPreviews();
  gotoStep(1);
  resultArea.className = "result-area empty";
  resultArea.innerHTML = `
    <div class="placeholder">
      <div class="ph-icon">📊</div>
      <p>请先上传答卷图片</p>
      <p class="hint">上传 → 确认 → 填写信息 → 开始判题</p>
    </div>`;
  toast("已清空", "info");
}

function onConfirm() {
  if (state.files.length === 0) return;
  state.confirmed = true;
  state.lastResults = null;
  toast(`✓ 已确认 ${state.files.length} 张答卷`, "ok");
  gotoStep(2);
}

function gotoStep(n) {
  if (n === 2 && !state.confirmed) { toast("请先点击“确认上传”", "warn"); return; }
  state.currentStep = n;
  stepItems.forEach(it => {
    const s = +it.dataset.step;
    it.classList.toggle("active", s === n);
    it.classList.toggle("done", s < n);
  });
  Object.entries(stepPanels).forEach(([k, el]) => {
    el.classList.toggle("active", +k === n);
  });
  if (n === 3) renderConfirmSummary();
}

function renderConfirmSummary() {
  const fs = state.files.length;
  const per = parseInt(fullScore.value) || 10;
  confirmSummary.innerHTML = `
    <div class="cs-row">
      <span class="cs-icon">📄</span>
      <div class="cs-text">
        <b>${fs}</b> 张答卷已确认<br/>
        <span class="cs-sub">${state.files.map(f => f.name).join("、")}</span>
      </div>
    </div>
    <div class="cs-row">
      <span class="cs-icon">🎯</span>
      <div class="cs-text">
        每题满分 <b>${per}</b> 分<br/>
        <span class="cs-sub">实际总分需等模型识别题数后确定（多题页总分 = 每题满分 × 题数）</span>
      </div>
    </div>
  `;
}

// ---------- 判题 ----------
// 统一入口：单张走 /api/judge；多张（点"批量判题"或多文件）逐张调用 /api/judge，
// 每张完成即更新进度条并增量渲染，失败不阻塞后面的卷子。

// 单次判题前端超时：5 分钟（后端 API 超时 180s × 最多 3 次重试，留足余量）
const JUDGE_TIMEOUT_MS = 5 * 60 * 1000;

// 把原始报错翻译成人话（答辩演示时评委/用户看得懂）
function friendlyError(err) {
  const m = String((err && err.message) || err || "");
  if (/Failed to fetch|NetworkError|network/i.test(m))
    return "网络连接失败：请检查后端服务是否已启动（运行 start_backend.ps1）";
  if (/timeout|aborted|TimeoutError|AbortError/i.test(m))
    return "请求超时：模型响应时间过长（复杂题可能需 1~3 分钟），请稍后重试";
  if (/Unexpected token|JSON/i.test(m))
    return "服务器返回了异常内容：后端可能正在重启，请稍后重试";
  return m;
}

// 判题期间的"模拟推进"：真实进度只有每张图完成才更新，
// 中间 1~3 分钟若进度条一动不动，用户会以为卡死——这里让它缓慢爬升到 92%
let fakeTimer = null;
function startFakeProgress(fromPct) {
  stopFakeProgress();
  let cur = fromPct;
  fakeTimer = setInterval(() => {
    if (cur >= 92) return;
    cur += 0.4;
    progressFill.style.width = cur + "%";
  }, 3000);
}
function stopFakeProgress() {
  if (fakeTimer) { clearInterval(fakeTimer); fakeTimer = null; }
}

async function doJudge(isBatch) {
  if (!state.files.length) { toast("请先上传答卷图片", "warn"); return; }
  if (!state.confirmed) { toast("请先点击“确认上传”", "warn"); return; }
  if (apiStatus.classList.contains("fail")) {
    toast("后端未连接，请先启动后端服务", "error", 3500);
    return;
  }

  btnJudge.disabled = btnBatch.disabled = true;
  showProgress(0, "准备上传...");
  // 结果区先放一个"判题中"占位，避免用户盯着空白干等
  resultArea.className = "result-area";
  resultArea.innerHTML = `
    <div class="placeholder">
      <div class="ph-icon" style="animation:spin 2s linear infinite">⏳</div>
      <p>AI 正在阅读答卷...</p>
      <p class="hint">识别 → 要素提取 → 知识图谱评估，通常需要 1~3 分钟</p>
    </div>`;

  const files = state.files;
  const results = [];
  let failCnt = 0;

  try {
    for (let i = 0; i < files.length; i++) {
      const pct = Math.round((i / files.length) * 100);
      showProgress(pct, `正在判题 ${i + 1} / ${files.length}：${files[i].name}（约需 1~3 分钟，请勿关闭页面）`);
      startFakeProgress(pct);
      const form = new FormData();
      form.append("file", files[i]);
      form.append("question_context", questionContext.value || "");
      form.append("full_score", fullScore.value || "10");
      try {
        const resp = await fetch(`${API_BASE}/api/judge`, {
          method: "POST", body: form,
          signal: AbortSignal.timeout(JUDGE_TIMEOUT_MS),   // F2: 超时保护
        });
        // F3: 后端返回非 JSON（如网关错误页）时给出可读提示，而不是 "Unexpected token"
        let data;
        try { data = await resp.json(); }
        catch { throw new Error(`服务器返回异常（HTTP ${resp.status}）`); }
        if (!data.success) throw new Error(data.error || "未知错误");
        results.push(data.data);
      } catch (err) {
        failCnt++;
        results.push({ image_name: files[i].name, error: friendlyError(err) });
      }
      stopFakeProgress();
      // 每张完成立即渲染（增量），用户不用干等全部结束
      renderResults(results, results.length > 1);
      if (window.MathJax?.typesetPromise) {
        window.MathJax.typesetPromise([resultArea]).catch(() => {});
      }
    }
    showProgress(100, `完成 ✓ 成功 ${results.length - failCnt} 张${failCnt ? ` · 失败 ${failCnt} 张` : ""}`);
    toast(`判题完成：成功 ${results.length - failCnt} 张${failCnt ? `，失败 ${failCnt} 张` : ""}`, failCnt ? "warn" : "ok");
    if (failCnt === files.length) {
      // 全部失败 → 给一条汇总的原因提示（多半是后端没启动 / Key 未配置 / 断网）
      const firstErr = results.find(r => r.error)?.error || "";
      toast(`失败原因：${firstErr}`, "error", 5000);
    }
  } catch (e) {
    toast(`判题失败: ${friendlyError(e)}`, "error", 3500);
    console.error(e);
  } finally {
    stopFakeProgress();
    btnJudge.disabled = btnBatch.disabled = false;
    setTimeout(() => hideProgress(), 1800);
  }
}

function showProgress(pct, text) {
  progress.classList.remove("hidden");
  progressFill.style.width = pct + "%";
  progressText.textContent = text;
}
function hideProgress() {
  progress.classList.add("hidden");
  progressFill.style.width = "0%";
}

// ---------- 结果渲染 ----------
function renderResults(data, isBatch) {
  resultArea.className = "result-area";
  resultArea.innerHTML = "";

  const items = Array.isArray(data) ? data : [data];
  items.forEach((r, idx) => {
    const card = document.createElement("div");
    card.className = "result-card";
    card.dataset.status = resultStatus(r);

    if (r.error) {
      card.innerHTML = `<div class="card-title">
        <h3>${r.image_name || "图片"}</h3>
        <span class="status-tag fail">失败</span>
      </div>
      <p style="color:#e74c3c">判题失败: ${r.error}</p>`;
      resultArea.appendChild(card);
      return;
    }

    const m1 = r.M1_feature || {};
    const m2 = r.M2_elements || {};
    const m3 = r.M3_judgment || {};

    card.innerHTML = `
      <div class="card-title">
        <h3>${idx + 1}. ${r.image_name || ""}
          ${m2.multi_problem ? `<span class="multi-tag">共${m3.problem_count || (m2.problems||[]).length}道题</span>` : ""}
        </h3>
        <div class="card-right">
          <button class="btn-export" data-action="export-csv" data-target="${idx}">📥 导出CSV</button>
          <span class="status-tag ${resultStatus(r)}">${statusLabel(resultStatus(r))}</span>
          <div class="score-big">${m3.total_score ?? "-"}<span class="full"> / ${m3.full_score ?? 10}</span></div>
        </div>
      </div>

      ${renderErrorStats(m3)}
      ${renderWeakCard(m3)}

      <h4 class="sub-h">📝 逐题判题详情</h4>
      ${renderProblemFolds(m1, m2, m3)}

      <h4 class="sub-h">🎓 整体教学反馈</h4>
      <div class="feedback">${escapeHtml(m3.feedback || "")}</div>

      <details style="margin-top:14px">
        <summary>查看完整 JSON</summary>
        <pre class="recognition">${escapeHtml(JSON.stringify(r, null, 2))}</pre>
      </details>
    `;
    resultArea.appendChild(card);
  });

  const tabs = $("#resultTabs");
  if (tabs) tabs.hidden = items.length <= 1;
  applyFilter("all");

  // 触发 MathJax 重新渲染公式
  if (window.MathJax && window.MathJax.typesetPromise) {
    window.MathJax.typesetPromise([resultArea]).catch(() => {});
  }
}

function resultStatus(r) {
  if (r.error) return "fail";
  const s = r.M3_judgment || {};
  if (s.total_score === undefined) return "fail";
  if (s.total_score >= s.full_score * 0.95) return "correct";
  if (s.total_score >= s.full_score * 0.6) return "partial";
  return "wrong";
}
function statusLabel(s) {
  return ({ correct: "✓ 全对", partial: "△ 有错", wrong: "✗ 错误", fail: "失败" })[s] || s;
}
function applyFilter(filter) {
  document.querySelectorAll(".result-card").forEach(c => {
    c.style.display = (filter === "all" || c.dataset.status === filter) ? "" : "none";
  });
}

// ---------- 错误分类卡片 ----------
function renderErrorStats(m3) {
  const e = m3.error_summary || {};
  const calc = e.calculation_error || 0;
  const conc = e.concept_error || 0;
  const logic = e.logic_gap || 0;
  return `
    <h4 class="sub-h">📊 错误分类统计</h4>
    <div class="err-stats">
      <div class="err-stat calculation">
        <div class="err-num">${calc}</div>
        <div class="err-label">计算错误</div>
        <div class="err-hint">数值运算出错</div>
      </div>
      <div class="err-stat concept">
        <div class="err-num">${conc}</div>
        <div class="err-label">概念错误</div>
        <div class="err-hint">原理/公式用错</div>
      </div>
      <div class="err-stat logic">
        <div class="err-num">${logic}</div>
        <div class="err-label">逻辑漏洞</div>
        <div class="err-hint">推理跳步</div>
      </div>
    </div>
  `;
}

// ---------- 薄弱知识点卡片 ----------
function renderWeakCard(m3) {
  const weak = m3.weak_knowledge_points || [];
  if (!weak.length) {
    return `<h4 class="sub-h">🧠 薄弱知识点</h4>
      <div class="weak-empty">本次答卷未识别到明显薄弱知识点</div>`;
  }
  return `
    <h4 class="sub-h">🧠 薄弱知识点</h4>
    <div class="weak-card">
      ${weak.map(w => `
        <div class="weak-row">
          <div class="weak-info">
            <b>${escapeHtml(w.node_name || w.node_id)}</b>
            <span class="mastery-badge">掌握度 ${Math.round((w.mastery||0)*100)}%</span>
          </div>
          <div class="weak-bar"><div class="weak-bar-fill" style="width:${Math.round((w.mastery||0)*100)}%"></div></div>
          <div class="weak-advice">${escapeHtml(w.advice || "")}</div>
        </div>
      `).join("")}
    </div>
  `;
}

// ---------- 逐题详情：题目序号导航 + 单题翻页 ----------
function renderProblemFolds(m1, m2, m3) {
  // 兼容：单题返回时 m2.problems 可能不存在，此时把单题包装为 1 个元素的数组
  const problems = (m2.problems && m2.problems.length)
    ? m2.problems
    : [{
        problem_index: 1,
        raw_text: m1.raw_text || "",
        known_conditions: m2.known_conditions || [],
        steps: m2.steps || [],
        final_answer: m2.final_answer || {},
        error_summary: m2.error_summary || {},
        involved_knowledge_points: m2.involved_knowledge_points || [],
        standard_reasoning_chain: m2.standard_reasoning_chain || "",
      }];

  const singlesByIdx = (m3.per_problem || []).reduce((acc, s) => {
    acc[s.problem_index] = s; return acc;
  }, {});
  const fullText = m1.raw_text || "";

  // ---- 题号导航条（带得分状态色点）----
  const chips = problems.map((p, i) => {
    const idx = p.problem_index || 1;
    const s = singlesByIdx[idx] || {};
    const score = s.total_score, full = s.full_score;
    const okAll = correct_count(p.steps) === (p.steps || []).length && (p.steps || []).length > 0;
    let cls = "mid";
    if (full && score !== undefined && score >= full * 0.99) cls = "ok";
    else if (okAll) cls = "ok";
    else if (score !== undefined && full && score < full * 0.6) cls = "bad";
    const scoreTxt = (score !== undefined && full) ? `${score}/${full}` : "";
    const activeCls = i === 0 ? " active" : "";
    return `
      <button class="pn-chip ${cls}${activeCls}" data-idx="${idx}" title="第${idx}题 ${scoreTxt}">
        <span class="pn-num">${idx}</span>
        ${scoreTxt ? `<span class="pn-score">${scoreTxt}</span>` : ""}
      </button>
    `;
  }).join("");

  // ---- 每题一页 ----
  const pages = problems.map((p, i) => {
    const idx = p.problem_index || 1;
    const pageActive = i === 0 ? " active" : "";
    const s = singlesByIdx[idx] || {};
    const score = s.total_score ?? "-";
    const full = s.full_score ?? "-";
    const errList = [];
    if (Array.isArray(s.error_reasons) && s.error_reasons.length) errList.push(...s.error_reasons);
    if (p.error_summary) {
      for (const [k, v] of Object.entries(p.error_summary)) {
        if (v > 0) errList.push(`${k}: ${v}`);
      }
    }
    const errStr = errList.join("；");
    const okAll = correct_count(p.steps) === (p.steps || []).length && (p.steps || []).length > 0;
    const noneRight = (p.steps || []).length > 0 && correct_count(p.steps) === 0;
    const tag = okAll ? "correct" : (noneRight ? "wrong" : "mid");

    const problemRaw = (p.problem_text && p.problem_text.length > 10)
      ? p.problem_text
      : extractProblemSegment(fullText, idx, problems.length);

    return `
      <div class="pn-page${pageActive}" data-idx="${idx}">
        <div class="pn-page-head">
          <b>📌 第${idx}题</b>
          <span class="pf-score ${tag === "mid" ? "" : tag}">${score} / ${full}</span>
          ${okAll ? `<span class="pf-pill ok">✓ 全对</span>`
            : (noneRight ? `<span class="pf-pill bad">✗ 全错</span>`
                         : `<span class="pf-pill mid">△ 部分对</span>`)}
        </div>

        ${renderProblemRecognition(problemRaw, p)}

        <div class="pf-section">
          <div class="pf-section-title">🪜 解题步骤</div>
          ${renderSteps(p.steps || [])}
        </div>

        <div class="pf-section">
          <div class="pf-section-title">📚 涉及知识点</div>
          ${(p.involved_knowledge_points && p.involved_knowledge_points.length)
            ? `<div class="kp-chips">${p.involved_knowledge_points.map(k =>
                `<span class="kp-chip">${escapeHtml(typeof k === 'string' ? k : (k.node_name || k.name || ''))}</span>`).join("")}</div>`
            : `<div class="muted">未识别到具体知识点</div>`}
        </div>

        ${errStr ? `<div class="pf-section">
          <div class="pf-section-title">⚠ 错误原因</div>
          <div class="err-reasons">${escapeHtml(errStr)}</div>
        </div>` : ""}

        ${(s.score_breakdown || []).length ? `<div class="pf-section">
          <div class="pf-section-title">📊 本题判分明细</div>
          ${(s.score_breakdown || []).map(b =>
            `<div class="pb-row"><span>${b.item}</span><span>${b.got} / ${b.full}</span><span class="pb-reason">${escapeHtml(b.reason || "")}</span></div>`
          ).join("")}
        </div>` : ""}
      </div>
    `;
  }).join("");

  const multi = problems.length > 1;
  return `
    <div class="problem-nav" ${multi ? "" : 'data-single="1"'}>
      ${multi ? `<button class="pn-arrow" data-dir="-1" title="上一题">◀</button>` : ""}
      <div class="pn-chips">${chips}</div>
      ${multi ? `<button class="pn-arrow" data-dir="1" title="下一题">▶</button>` : ""}
    </div>
    <div class="pn-pages">${pages}</div>
  `;
}

function correct_count(steps) {
  return (steps || []).filter(s => String(s.verdict || "").toLowerCase() === "correct").length;
}

// 从 M1 完整 raw_text 中切出第 k 题的段落（多题页时按 (1)(2) 等题号切分）
function extractProblemSegment(fullText, k, total) {
  if (!fullText || total <= 1) return fullText || "";
  // 匹配 (k) 或 （k） 开头到下一个题号 / 末尾
  const head = String(k);
  const re = new RegExp(
    `(?:\\(\\s*${head}\\s*\\)|（\\s*${head}\\s*）|第\\s*${head}\\s*题|\\n\\s*${head}\\s*[\\.、])`,
    "i"
  );
  const m = re.exec(fullText);
  if (!m) return "";
  const start = m.index;
  const next = new RegExp(
    `(?:\\(\\s*${k + 1}\\s*\\)|（\\s*${k + 1}\\s*）|第\\s*${k + 1}\\s*题|\\n\\s*${k + 1}\\s*[\\.、])`,
    "i"
  );
  const m2 = next.exec(fullText);
  const end = m2 ? m2.index : fullText.length;
  return fullText.slice(start, end).trim();
}

// ---------- 识别文本渲染（MathJax 内嵌 + 低置信度标黄） ----------
function renderProblemRecognition(segment, problem) {
  if (!segment) return `<div class="recognition muted">（该题未识别到内容）</div>`;
  const text = markLowConfidence(escapeHtml(segment));
  return `<div class="recognition">${text}</div>`;
}

// 低置信度标记：对含模糊标记的片段包黄底提示
// 判定规则（毕设启发式）：包含 [?] ?? (?) 【?】 ... 看不清 字迹模糊 等关键词的整段
function markLowConfidence(htmlText) {
  const patterns = [
    /\[ ?\? ?\]/g, /\?\?+/g, /\(\s*\?\s*\)/g, /【\s*\?\s*】/g,
    /\.\.\./g, /字迹模糊/g, /看不清/g, /（\s*未\s*）/g, /识别不清/g,
  ];
  let out = htmlText;
  patterns.forEach(re => {
    out = out.replace(re, m => `<span class="low-conf" title="识别可信度较低，建议人工核对">${m}</span>`);
  });
  // 极端短的疑似错字（孤立 ? 或孤立单个奇怪字符）—— 谨慎处理，仅当原文就是这些符号时
  return out;
}

// ---------- 解题步骤 ----------
function renderSteps(steps) {
  if (!steps.length) return "<div class='step'>（模型未识别到解题步骤）</div>";
  return steps.map(s => {
    const verdict = (s.verdict || "uncertain").toLowerCase();
    const et = s.error_type && s.error_type !== "null"
      ? `<div class="err-type">错误类型：${escapeHtml(s.error_type)}</div>` : "";
    return `
      <div class="step ${verdict}">
        <div class="head">
          <span>步骤 ${s.step_id}: ${escapeHtml(s.content || "")}</span>
          <span class="badge">${verdict}</span>
        </div>
        <div>中间结果: <code>${escapeHtml(s.result || "")}</code></div>
        ${et}
        <div class="reason">${escapeHtml(s.reason || "")}</div>
      </div>
    `;
  }).join("");
}

// ---------- 导出 CSV ----------
function exportCsv(targetIdx) {
  if (!state.lastResults) return;
  const items = Array.isArray(state.lastResults) ? state.lastResults : [state.lastResults];
  const r = items[+targetIdx];
  if (!r) return;

  const m1 = r.M1_feature || {};
  const m2 = r.M2_elements || {};
  const m3 = r.M3_judgment || {};

  // 把 per_problem 扁平化为表格行（每题一行）；单题则为一行
  const rows = [["文件名", "题号", "本题得分", "本题满分", "最终答案", "判定",
                 "计算错误数", "概念错误数", "逻辑漏洞数", "涉及知识点", "错误原因"]];

  if (m2.multi_problem && Array.isArray(m3.per_problem)) {
    m3.per_problem.forEach(p => {
      const e = p.error_summary || {};
      rows.push([
        r.image_name || "",
        `第${p.problem_index}题`,
        p.total_score ?? "",
        p.full_score ?? "",
        (p.final_answer || {}).value || "",
        (p.final_answer || {}).verdict || "",
        e.calculation_error || 0,
        e.concept_error || 0,
        e.logic_gap || 0,
        (p.involved_knowledge_points || []).map(k => k.node_name || k).join(" / "),
        (p.error_reasons || []).join("；"),
      ]);
    });
    rows.push(["---总分---", "—", m3.total_score, m3.full_score, "", "", "", "", "", "", ""]);
  } else {
    const e = m2.error_summary || {};
    rows.push([
      r.image_name || "",
      "1",
      m3.total_score ?? "",
      m3.full_score ?? "",
      (m2.final_answer || {}).value || "",
      (m2.final_answer || {}).verdict || "",
      e.calculation_error || 0,
      e.concept_error || 0,
      e.logic_gap || 0,
      (m2.involved_knowledge_points || []).join(" / "),
      (m3.error_reasons || []).join("；"),
    ]);
  }

  const csv = rows.map(row => row.map(csvCell).join("; ")).join("\n");
  // 加 BOM 让 Excel 正确识别 UTF-8
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  a.download = `${(r.image_name || "judge").replace(/\.[^.]+$/, "")}_${ts}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  toast("✓ CSV 已下载", "ok");
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const s = String(v).replace(/"/g, '""');
  return /[",;\n]/.test(s) ? `"${s}"` : s;
}

// ---------- 工具 ----------
function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ============================================================
// =============== 学情分析页（页面 2） ==========================
// ============================================================

const analytics = {
  loaded: false,
  charts: {},   // 缓存 ECharts 实例
  range: 30,
  data: {},     // 当前周期的数据缓存
};

// 颜色 / 通用 ECharts 配置
const C = {
  primary: "#4f6dff",
  success: "#1fa860",
  warn:    "#f39c12",
  danger:  "#e74c3c",
  info:    "#3aa3ff",
  text:    "#2c3e72",
  grid:    "#eef2ff",
};
const CHART_TEXT_STYLE = { fontFamily: 'inherit', color: C.text };
const TOOLTIP_BASE = {
  backgroundColor: "rgba(28,28,40,0.92)",
  borderColor: "transparent",
  textStyle: { color: "#fff", fontSize: 12 },
  extraCssText: "box-shadow:0 4px 14px rgba(0,0,0,0.18);border-radius:8px;",
};

function loadAnalytics() {
  analytics.loaded = true;
  applyAnalyticsRange();
}

function applyAnalyticsRange() {
  const sel = document.getElementById("rangeSel");
  if (sel) analytics.range = parseInt(sel.value) || 30;
  const sub = document.getElementById("tbSub");
  if (sub) sub.textContent = `数据范围：最近 ${analytics.range} 天`;
  refreshAnalytics();
}

function disposeAnalyticsCharts() {
  Object.values(analytics.charts).forEach(c => { try { c.dispose(); } catch {} });
  analytics.charts = {};
}

async function refreshAnalytics() {
  if (!window.echarts) {
    // ECharts 加载失败（CDN 被墙/断网且本地副本缺失）→ 图表区全部会空白，
    // 这里用明显的错误状态代替静默失败，告诉用户怎么修
    toggleEmpty(false, "图表库（ECharts）加载失败：请按 Ctrl+F5 强制刷新页面（本地已内置图表库，强刷后即可离线使用）");
    toast("ECharts 加载失败，请 Ctrl+F5 强制刷新", "error", 4000);
    return;
  }
  const days = analytics.range;
  const base = API_BASE;

  // 加载态
  const tb = document.getElementById("recentTbody");
  if (tb) tb.innerHTML = `<tr><td colspan="10" class="empty"><span class="spinner" style="display:inline-block;vertical-align:middle;margin-right:8px"></span>正在加载判题记录...</td></tr>`;

  try {
    // 并发拉取全部数据
    const [ovR, trR, distR, kpR, recR, gsR] = await Promise.all([
      fetch(`${base}/api/analytics/overview?days=${days}`).then(r => r.json()),
      fetch(`${base}/api/analytics/trend?days=${days}`).then(r => r.json()),
      fetch(`${base}/api/analytics/distribution?days=${days}`).then(r => r.json()),
      fetch(`${base}/api/analytics/knowledge?days=${days}`).then(r => r.json()),
      fetch(`${base}/api/analytics/recent?limit=20`).then(r => r.json()),
      fetch(`${base}/api/analytics/graph_stats?days=${days}`).then(r => r.json()),
    ]);

    // 任一接口失败（如后端未重启 404）→ 显示空状态引导
    if (!ovR.success) throw new Error(ovR.error || "接口返回失败");

    analytics.data = {
      overview: ovR.data, trend: trR.success ? trR.data : null,
      dist: distR.success ? distR.data : null,
      kp: kpR.success ? kpR.data : null,
      recent: recR.success ? recR.data : null,
      graph: gsR.success ? gsR.data : null,
    };

    renderKpi(ovR.data);
    const hasData = (ovR.data.paper_count || 0) > 0;
    toggleEmpty(hasData);
    if (!hasData) return;

    if (analytics.data.trend) renderTrend(analytics.data.trend);
    if (analytics.data.dist) renderDist(analytics.data.dist);
    if (analytics.data.kp) { renderErrPie(ovR.data.error_totals); renderKpBar(analytics.data.kp); }
    if (analytics.data.graph) renderGraph(analytics.data.graph);
    if (analytics.data.recent) renderRecent(analytics.data.recent);

    // 渲染完成后统一 resize 一次（防止容器尺寸变化导致的绘制异常）
    requestAnimationFrame(() => {
      Object.values(analytics.charts).forEach(c => { try { c.resize(); } catch {} });
    });
    // 二次兜底：页面切换动画/布局抖动后 300ms 再校准一次，力导向图尤其需要
    setTimeout(() => {
      Object.values(analytics.charts).forEach(c => { try { c.resize(); } catch {} });
    }, 300);
  } catch (e) {
    console.error(e);
    toggleEmpty(false, e.message);
    toast(`学情分析加载失败：${e.message}`, "error", 3000);
  }
}

// 数据为空 / 接口失败时显示引导卡片，隐藏图表区
function toggleEmpty(hasData, errMsg) {
  const page = document.getElementById("page-analytics");
  if (!page) return;
  let empty = page.querySelector(".analytics-empty");
  const blocks = page.querySelectorAll(".kpi-grid, .chart-row");
  if (hasData) {
    if (empty) empty.remove();
    blocks.forEach(b => { b.style.display = ""; });
    return;
  }
  if (!empty) {
    empty = document.createElement("div");
    empty.className = "analytics-empty";
    empty.innerHTML = `
      <div class="ae-icon">📭</div>
      <h3>${errMsg ? "数据加载失败" : "暂无学情数据"}</h3>
      <p>${errMsg
        ? `${escapeHtml(errMsg)}<br/>请确认后端已重启（新接口需要重启后端生效），然后点击刷新。`
        : "还没有判过任何答卷。<br/>先到【答卷判题】页上传并判题，这里就会自动生成统计图表和知识图谱。"}</p>
      <button class="btn primary" onclick="switchPage('judge')">📷 去判题</button>
    `;
    // 插到工具栏后面
    const toolbar = page.querySelector(".analytics-toolbar");
    toolbar.after(empty);
  } else {
    // 更新错误信息
    const h3 = empty.querySelector("h3");
    const p = empty.querySelector("p");
    if (h3) h3.textContent = errMsg ? "数据加载失败" : "暂无学情数据";
    if (p) p.innerHTML = errMsg
      ? `${escapeHtml(errMsg)}<br/>请确认后端已重启，然后点击刷新。`
      : "还没有判过任何答卷。先到【答卷判题】页上传并判题。";
  }
  blocks.forEach(b => { b.style.display = "none"; });
}

// ---------- KPI 卡片 ----------
function renderKpi(d) {
  setText("kpiPaper",     d.paper_count);
  setText("kpiPaperFoot", `共 ${d.paper_count} 张 · ${d.days} 天`);
  setText("kpiProblem",   d.problem_count);
  setText("kpiProblemFoot", `单题 ${d.single_problem_count} · 多题页 ${d.multi_problem_count}`);
  setText("kpiAvgRate",   (d.avg_score_rate * 100).toFixed(1) + "%");
  setText("kpiAvgRateFoot", `平均得分 ${d.avg_score}`);
  setText("kpiPass",      (d.pass_rate * 100).toFixed(1) + "%");
  setText("kpiPassFoot",  `${d.pass_count} / ${d.paper_count} 张及格`);
  const e = d.error_totals || {};
  const totalErr = (e.logic_gap||0) + (e.calculation_error||0) + (e.concept_error||0);
  setText("kpiErr",       totalErr);
  setText("kpiErrFoot",   `逻辑 ${e.logic_gap||0} · 计算 ${e.calculation_error||0} · 概念 ${e.concept_error||0}`);
}
function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }

// ---------- 趋势折线 ----------
function renderTrend(d) {
  const el = document.getElementById("chartTrend");
  if (!el) return;
  let c = analytics.charts.trend;
  if (!c) { c = analytics.charts.trend = echarts.init(el, null, { renderer: "canvas" }); }
  const series = d.series || [];
  c.setOption({
    textStyle: CHART_TEXT_STYLE,
    tooltip: { ...TOOLTIP_BASE, trigger: "axis" },
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: "category",
      data: series.map(s => s.day.slice(5)),
      axisLine: { lineStyle: { color: "#dde3f0" } },
      axisLabel: { color: "#888", fontSize: 11 },
    },
    yAxis: {
      type: "value", min: 0, max: 1,
      axisLabel: { formatter: v => Math.round(v * 100) + "%", color: "#888", fontSize: 11 },
      splitLine: { lineStyle: { color: C.grid } },
    },
    series: [
      {
        name: "得分率",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: series.map(s => s.avg_rate),
        lineStyle: { width: 3, color: C.primary },
        itemStyle: { color: C.primary },
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(79,109,255,0.30)" }, { offset: 1, color: "rgba(79,109,255,0.02)" }] },
        },
      },
    ],
  });
}

// ---------- 得分率分布 ----------
function renderDist(d) {
  const el = document.getElementById("chartDist");
  if (!el) return;
  let c = analytics.charts.dist;
  if (!c) { c = analytics.charts.dist = echarts.init(el); }
  const buckets = d.buckets || [];
  c.setOption({
    textStyle: CHART_TEXT_STYLE,
    tooltip: { ...TOOLTIP_BASE, trigger: "axis",
      formatter: p => `${p[0].name}<br/>答卷数：<b>${p[0].value}</b>` },
    grid: { left: 40, right: 16, top: 16, bottom: 30 },
    xAxis: {
      type: "category", data: buckets.map(b => b.label),
      axisLabel: { color: "#888", fontSize: 11 },
      axisLine: { lineStyle: { color: "#dde3f0" } },
    },
    yAxis: {
      type: "value", axisLabel: { color: "#888" },
      splitLine: { lineStyle: { color: C.grid } },
    },
    series: [{
      type: "bar",
      data: buckets.map(b => ({
        value: b.count,
        itemStyle: {
          color: b.max <= 0.6 ? C.danger : (b.max <= 0.8 ? C.warn : C.success),
          borderRadius: [6, 6, 0, 0],
        },
      })),
      barCategoryGap: "35%",
      label: { show: true, position: "top", color: "#666", fontSize: 11 },
    }],
  });
}

// ---------- 错误类型饼图 ----------
function renderErrPie(e) {
  const el = document.getElementById("chartErrPie");
  if (!el) return;
  let c = analytics.charts.errPie;
  if (!c) { c = analytics.charts.errPie = echarts.init(el); }
  const data = [
    { name: "计算错误", value: e.calculation_error || 0, itemStyle: { color: C.danger } },
    { name: "概念错误", value: e.concept_error || 0,     itemStyle: { color: C.warn } },
    { name: "逻辑漏洞", value: e.logic_gap || 0,         itemStyle: { color: C.info } },
  ];
  const total = data.reduce((s, x) => s + x.value, 0);
  c.setOption({
    textStyle: CHART_TEXT_STYLE,
    tooltip: { ...TOOLTIP_BASE, trigger: "item",
      formatter: p => `${p.name}<br/>数量：<b>${p.value}</b><br/>占比：<b>${total ? (p.value/total*100).toFixed(1) : 0}%</b>` },
    legend: { bottom: 0, textStyle: { color: "#555" } },
    series: [{
      type: "pie",
      radius: ["38%", "68%"],
      center: ["50%", "45%"],
      avoidLabelOverlap: true,
      label: { formatter: "{b}\n{d}%", color: "#555", fontSize: 12 },
      data,
      emphasis: {
        itemStyle: { shadowBlur: 12, shadowColor: "rgba(0,0,0,0.18)" },
      },
    }],
  });
}

// ---------- 知识点薄弱 TOP10 ----------
function renderKpBar(d) {
  const el = document.getElementById("chartKpBar");
  if (!el) return;
  let c = analytics.charts.kpBar;
  if (!c) { c = analytics.charts.kpBar = echarts.init(el); }
  // 只显示有数据的；按错误率降序；最多 10 个
  const items = (d.items || []).filter(x => x.total_count > 0)
                                .sort((a, b) => b.error_rate - a.error_rate)
                                .slice(0, 10)
                                .reverse(); // 反转让最薄弱在最上面
  const maxRate = items.length ? Math.max(...items.map(x => x.error_rate), 0.1) : 1;
  c.setOption({
    textStyle: CHART_TEXT_STYLE,
    tooltip: {
      ...TOOLTIP_BASE, trigger: "axis",
      formatter: p => {
        const it = items[p[0].dataIndex];
        return `<b>${it.node_name}</b><br/>考核 ${it.total_count} 次 · 错误 ${it.error_count} 次<br/>错误率：<b>${(it.error_rate*100).toFixed(1)}%</b> · 掌握度 ${(it.mastery*100).toFixed(1)}%`;
      },
    },
    grid: { left: 100, right: 30, top: 10, bottom: 24 },
    xAxis: {
      type: "value", max: Math.ceil(maxRate * 10) / 10 || 1,
      axisLabel: { formatter: v => Math.round(v * 100) + "%", color: "#888", fontSize: 11 },
      splitLine: { lineStyle: { color: C.grid } },
    },
    yAxis: {
      type: "category", data: items.map(x => x.node_name || x.node_id),
      axisLabel: { color: "#444", fontSize: 12 },
      axisLine: { lineStyle: { color: "#dde3f0" } },
    },
    series: [{
      type: "bar",
      data: items.map(x => ({
        value: x.error_rate,
        itemStyle: {
          color: x.error_rate >= 0.4 ? C.danger : (x.error_rate >= 0.2 ? C.warn : C.success),
          borderRadius: [0, 6, 6, 0],
        },
      })),
      label: {
        show: true, position: "right", color: "#666", fontSize: 11,
        formatter: p => (p.value * 100).toFixed(0) + "%",
      },
      barCategoryGap: "40%",
    }],
  });
}

// ---------- 知识图谱 ----------
function renderGraph(d) {
  const el = document.getElementById("chartGraph");
  if (!el) return;
  // 兜底：容器尚未完成布局（宽/高为 0）时 echarts 会画在零尺寸画布上 → 看起来空白。
  // 延迟重试一次，等布局完成再初始化。
  if (!el.clientWidth || !el.clientHeight) {
    setTimeout(() => renderGraph(d), 200);
    return;
  }
  // 图谱实例总是废弃重建：实例若在标签页切换（容器 display:none）等异常时机被初始化，
  // 内部布局状态可能损坏（力布局算出 NaN 坐标 → 画布永久空白，且 resize 也无法恢复）。
  // 图谱初始化成本很低，重建是最稳妥的修复方式。
  try { if (analytics.charts.graph && !analytics.charts.graph.isDisposed()) analytics.charts.graph.dispose(); } catch {}
  analytics.charts.graph = null;
  const c = analytics.charts.graph = echarts.init(el);

  const g = d.graph || { nodes: [], edges: [] };
  // 节点颜色按掌握度
  const nodes = g.nodes.map(n => {
    let color = "#bbb"; // 未考核
    if (n.tested) {
      if (n.mastery >= 0.8) color = C.success;
      else if (n.mastery >= 0.6) color = C.warn;
      else color = C.danger;
    }
    return {
      id: n.id, name: n.name, value: n.total_count || 0,
      symbolSize: 18 + (n.tested ? Math.min(20, Math.sqrt(n.total_count) * 4) : 0),
      itemStyle: { color, borderColor: "#fff", borderWidth: 2 },
      label: { show: true, color: "#333", fontSize: 12, fontWeight: 600 },
      tested: n.tested, mastery: n.mastery, error_rate: n.error_rate,
      total_count: n.total_count, error_count: n.error_count,
      difficulty: n.difficulty,
    };
  });
  const edges = g.edges.map(e => ({
    source: e.source, target: e.target,
    lineStyle: {
      color: e.type === "prerequisite" ? "#4f6dff" : "#bbb",
      width: e.type === "prerequisite" ? 1.4 : 1,
      curveness: 0.15,
      opacity: 0.7,
    },
  }));

  c.setOption({
    textStyle: CHART_TEXT_STYLE,
    tooltip: {
      ...TOOLTIP_BASE, trigger: "item",
      formatter: p => {
        if (!p.data || !p.data.tested) {
          return `<b>${p.data?.name || p.name}</b><br/>尚未考核`;
        }
        const d = p.data;
        return `<b>${d.name}</b><br/>考核 ${d.total_count} 次 · 错误 ${d.error_count} 次<br/>错误率 ${(d.error_rate*100).toFixed(1)}% · 掌握度 ${(d.mastery*100).toFixed(1)}%<br/>难度 ${"★".repeat(d.difficulty || 1)}`;
      },
    },
    // 注意：不要设置 legend 和 data.category——
    // graph 系列的 legend 依赖 series.categories，缺失时会导致整个系列渲染异常（画布空白）。
    // 页面底部已有静态 HTML 图例（.graph-legend），无需 ECharts 图例。
    series: [{
      type: "graph",
      layout: "force",
      data: nodes,
      links: edges,
      roam: true,
      force: { repulsion: 260, edgeLength: 110, gravity: 0.05 },
      emphasis: { focus: "adjacency" },
      edgeSymbol: ["none", "arrow"],
      edgeSymbolSize: 8,
    }],
  });
  // 兜底：若渲染异常（如个别版本兼容问题），打印明确日志便于定位
  c.on("finished", () => {
    try {
      const s = c.getModel().getSeriesByIndex(0);
      const layout = s && s.getData().getItemLayout(0);
      if (s && s.getData().count() > 0 && (!layout || isNaN(layout[0]))) {
        console.warn("[图谱] 布局坐标异常，请检查节点/边数据");
      }
    } catch {}
  });
}

// ---------- 最近判题表 ----------
function renderRecent(d) {
  const tbody = document.getElementById("recentTbody");
  if (!tbody) return;
  const items = d.items || [];
  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty">📭 暂无判题记录，请先去【答卷判题】页上传答卷</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((r, i) => {
    const e = (r.error_logic || 0) + (r.error_calculation || 0) + (r.error_concept || 0);
    const wps = (r.weak_points || []).length;
    const passTag = r.is_pass
      ? `<span class="tag pass">✓ 及格</span>`
      : `<span class="tag fail">✗ 未及格</span>`;
    return `
      <tr>
        <td>${i + 1}</td>
        <td title="${escapeHtml(r.image_name || "")}">${escapeHtml((r.image_name || "").slice(0, 22))}</td>
        <td>${r.is_multi_problem ? `${r.problem_count}题` : "单题"}</td>
        <td><b>${r.total_score}</b> / ${r.full_score}</td>
        <td>
          <div class="rate-cell">
            <div class="rate-bar"><div class="rate-fill" style="width:${(r.score_rate*100).toFixed(1)}%;background:${r.score_rate>=0.85?C.success:(r.score_rate>=0.6?C.warn:C.danger)}"></div></div>
            <span class="rate-num">${(r.score_rate*100).toFixed(1)}%</span>
          </div>
        </td>
        <td>${e > 0 ? `${r.error_calculation||0}计 / ${r.error_concept||0}概 / ${r.error_logic||0}逻` : "<span class='muted'>—</span>"}</td>
        <td>${wps > 0 ? `<span class="muted">${wps} 个</span>` : "<span class='muted'>—</span>"}</td>
        <td>${passTag}</td>
        <td>${(r.duration_ms/1000).toFixed(1)}s</td>
        <td>${(r.created_at || "").replace("T", " ").slice(0, 16)}</td>
      </tr>
    `;
  }).join("");
}

// 事件：周期切换 / 刷新
document.addEventListener("change", (e) => {
  if (e.target && e.target.id === "rangeSel") applyAnalyticsRange();
});
document.addEventListener("click", (e) => {
  const t = e.target.closest("#btnRefresh");
  if (!t) return;
  toast("正在刷新...", "info");
  refreshAnalytics();
});

// 窗口大小变化时重绘图表（防变形）
window.addEventListener("resize", () => {
  if (!analytics.loaded) return;
  Object.values(analytics.charts).forEach(c => { try { c.resize(); } catch {} });
});