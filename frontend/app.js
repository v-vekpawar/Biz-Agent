// ============================================================================
// The Desk — frontend logic for the multi-agent business-planning backend.
//
// Talks to three endpoints on the FastAPI backend (see backend/app/main.py):
//   POST /submit               multipart: request (text), document (file, optional)
//                               -> { job_id, status }
//   GET  /result/{job_id}      -> { job_id, status: pending|running|done|error, ... }
//                               when status === "done", also spreads the full
//                               run record: run_id, request, document_uploaded,
//                               document_chunk_count, orchestrator_plan, steps,
//                               retry_counts, final_report, final_report_markdown
//   GET  /result/{job_id}/pdf  -> PDF file (only valid once status === "done")
// ============================================================================

const DEFAULT_API_BASE = "http://localhost:8000";
const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 6 * 60 * 1000; // 6 minutes — generous for a cold free-tier run

// Visual identity per agent node, keyed by the backend's `node` field.
const ROLE_STYLES = {
  orchestrator:      { label: "Orchestrator",      icon: "◆", border: "border-indigo-500",  chip: "bg-indigo-100 text-indigo-900" },
  market_researcher: { label: "Market Researcher", icon: "◈", border: "border-teal-500",    chip: "bg-teal-100 text-teal-900" },
  financial_analyst: { label: "Financial Analyst", icon: "◉", border: "border-emerald-500", chip: "bg-emerald-100 text-emerald-900" },
  risk_assessor:     { label: "Risk Assessor",     icon: "▲", border: "border-rose-500",    chip: "bg-rose-100 text-rose-900" },
  strategist:        { label: "Strategist",        icon: "◎", border: "border-amber-500",   chip: "bg-amber-100 text-amber-900" },
  copywriter:        { label: "Copywriter",        icon: "✎", border: "border-fuchsia-500", chip: "bg-fuchsia-100 text-fuchsia-900" },
  ops_planner:       { label: "Ops Planner",       icon: "■", border: "border-sky-500",     chip: "bg-sky-100 text-sky-900" },
  synthesizer:       { label: "Synthesizer",       icon: "★", border: "border-ink",         chip: "bg-ink text-paper" },
};
const FALLBACK_ROLE_STYLE = { label: "Agent", icon: "•", border: "border-ink/40", chip: "bg-ink/10 text-ink" };

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentJobId = null;
let pollHandle = null;
let pollStartedAt = null;
let elapsedHandle = null;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const el = (id) => document.getElementById(id);

const requestForm = el("requestForm");
const requestText = el("requestText");
const documentFile = el("documentFile");
const fileLabel = el("fileLabel");
const submitBtn = el("submitBtn");
const formError = el("formError");

const statusSection = el("statusSection");
const jobIdBadge = el("jobIdBadge");
const statusMessage = el("statusMessage");
const statusLine = el("statusLine");
const statusError = el("statusError");
const elapsedTime = el("elapsedTime");
const progressLine1 = el("progressLine1");
const progressLine2 = el("progressLine2");
const stepRunning = el("stepRunning");
const stepDone = el("stepDone");

const resultsSection = el("resultsSection");
const tabReport = el("tabReport");
const tabLog = el("tabLog");
const pdfLink = el("pdfLink");

// ---------------------------------------------------------------------------
// Small utilities
// ---------------------------------------------------------------------------
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Turns plain agent-written text into safe, lightly-structured HTML:
// blank-line-separated paragraphs, "- " lines become a bullet list.
function renderTextBlock(text) {
  if (!text) return "";
  const blocks = String(text).trim().split(/\n\s*\n/);
  return blocks
    .map((block) => {
      const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
      const isList = lines.length > 0 && lines.every((l) => /^[-*]\s+/.test(l));
      if (isList) {
        const items = lines.map((l) => `<li>${escapeHtml(l.replace(/^[-*]\s+/, ""))}</li>`).join("");
        return `<ul class="list-disc pl-5 space-y-1 my-2">${items}</ul>`;
      }
      return `<p class="my-2 leading-relaxed">${escapeHtml(block).replaceAll("\n", "<br>")}</p>`;
    })
    .join("");
}

function fmtSeconds(totalSeconds) {
  const s = Math.floor(totalSeconds % 60);
  const m = Math.floor(totalSeconds / 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function apiUrl(path) {
  return API_BASE.replace(/\/+$/, "") + path;
}

// ---------------------------------------------------------------------------
// File input label
// ---------------------------------------------------------------------------
documentFile.addEventListener("change", () => {
  const file = documentFile.files[0];
  fileLabel.innerHTML = file
    ? `Attached: <span class="font-mono">${escapeHtml(file.name)}</span>`
    : `Attach a document <span class="text-ink/45">(optional, PDF/TXT)</span>`;
});

// ---------------------------------------------------------------------------
// Submit flow
// ---------------------------------------------------------------------------
requestForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  hide(formError);

  const requestValue = requestText.value.trim();
  if (!requestValue) {
    showError(formError, "Describe the request before dispatching the agents.");
    return;
  }

  const formData = new FormData();
  formData.append("request", requestValue);
  if (documentFile.files[0]) {
    formData.append("document", documentFile.files[0]);
  }

  setSubmitting(true);

  try {
    const res = await fetch(apiUrl("/submit"), { method: "POST", body: formData });
    if (!res.ok) {
      const detail = await safeErrorDetail(res);
      throw new Error(detail || `Backend returned ${res.status}`);
    }
    const data = await res.json();
    currentJobId = data.job_id;
    beginTracking(currentJobId);
  } catch (err) {
    showError(
      formError,
      `Couldn't reach the backend at ${API_BASE}. ${err.message || err}.`
    );
  } finally {
    setSubmitting(false);
  }
});

function setSubmitting(isSubmitting) {
  submitBtn.disabled = isSubmitting;
  submitBtn.textContent = isSubmitting ? "Dispatching…" : "Dispatch agents →";
}

async function safeErrorDetail(res) {
  try {
    const body = await res.json();
    return body.detail;
  } catch {
    return null;
  }
}

function showError(node, message) {
  node.textContent = message;
  node.classList.remove("hidden");
}
function hide(node) {
  node.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Status tracking / polling
// ---------------------------------------------------------------------------
function beginTracking(jobId) {
  resultsSection.classList.add("hidden");
  statusError.classList.add("hidden");
  statusSection.classList.remove("hidden");
  jobIdBadge.textContent = `job ${jobId}`;
  setStage("submitted");
  statusLine.classList.remove("hidden");
  statusMessage.textContent = "Queued — waiting for a worker to pick this up…";
  statusSection.scrollIntoView({ behavior: "smooth", block: "start" });

  pollStartedAt = Date.now();
  clearInterval(elapsedHandle);
  elapsedHandle = setInterval(() => {
    elapsedTime.textContent = fmtSeconds((Date.now() - pollStartedAt) / 1000);
  }, 1000);

  clearInterval(pollHandle);
  pollHandle = setInterval(() => pollOnce(jobId), POLL_INTERVAL_MS);
  pollOnce(jobId); // fire immediately, don't wait for the first interval tick
}

async function pollOnce(jobId) {
  if (Date.now() - pollStartedAt > POLL_TIMEOUT_MS) {
    stopPolling();
    failStatus(
      "Still running after several minutes. Free-tier LLM/search APIs can be slow under " +
      "load — you can keep waiting by refreshing, or check the backend logs for the job."
    );
    return;
  }

  try {
    const res = await fetch(apiUrl(`/result/${jobId}`));
    if (!res.ok) {
      const detail = await safeErrorDetail(res);
      throw new Error(detail || `Backend returned ${res.status}`);
    }
    const data = await res.json();

    if (data.status === "pending") {
      setStage("submitted");
      statusMessage.textContent = "Queued — waiting for a worker to pick this up…";
    } else if (data.status === "running") {
      setStage("running");
      statusMessage.textContent = "Agents are working the case — orchestrating, researching, verifying…";
    } else if (data.status === "done") {
      setStage("done");
      stopPolling();
      renderResults(data);
    } else if (data.status === "error") {
      stopPolling();
      failStatus(data.error || "The pipeline raised an unhandled error.");
    }
  } catch (err) {
    stopPolling();
       failStatus(`Lost contact with the backend at ${API_BASE}. ${err.message || err}`);
  }
}

function stopPolling() {
  clearInterval(pollHandle);
  clearInterval(elapsedHandle);
  pollHandle = null;
}

function failStatus(message) {
  statusLine.classList.add("hidden");
  showError(statusError, message);
}

function setStage(stage) {
  const nodes = { submitted: el("stepSubmitted"), running: stepRunning, done: stepDone };
  const order = ["submitted", "running", "done"];
  const reached = order.indexOf(stage);

  order.forEach((key, i) => {
    const dot = nodes[key].querySelector("div");
    const label = nodes[key].querySelector("div:last-child");
    if (i <= reached) {
      dot.className = "mx-auto w-3 h-3 rounded-full bg-ink mb-1.5";
      label.className = "text-[11px] font-mono uppercase tracking-wide text-ink/70";
    } else {
      dot.className = "mx-auto w-3 h-3 rounded-full bg-ink/25 mb-1.5";
      label.className = "text-[11px] font-mono uppercase tracking-wide text-ink/40";
    }
  });

  if (stage === "running") {
    nodes.running.querySelector("div").classList.add("pulse-dot");
  }

  progressLine1.style.width = reached >= 1 ? "100%" : "0%";
  progressLine2.style.width = reached >= 2 ? "100%" : "0%";

  if (stage === "done") {
    const spinner = statusLine.querySelector(".spinner");
    if (spinner) spinner.outerHTML = `<span class="text-emerald-700 text-lg leading-none">✓</span>`;
    statusMessage.textContent = "Report ready.";
  }
}

// ---------------------------------------------------------------------------
// Results rendering
// ---------------------------------------------------------------------------
function renderResults(record) {
  pdfLink.href = apiUrl(`/result/${record.job_id}/pdf`);
  resultsSection.classList.remove("hidden");
  renderReportTab(record);
  renderLogTab(record);
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderReportTab(record) {
  const report = record.final_report || {};
  const sections = Array.isArray(report.sections) ? report.sections : [];
  const checklist = Array.isArray(report.checklist) ? report.checklist : [];

  const docNote = record.document_uploaded
    ? `<span class="inline-flex items-center gap-1.5 text-xs font-mono text-ink/50 border border-ink/20 rounded-full px-3 py-1">
         📎 grounded on ${record.document_chunk_count ?? "?"} document chunk(s)
       </span>`
    : "";

  const sectionsHtml = sections.length
    ? sections
        .map((s) => {
          const style = ROLE_STYLES[s.specialist] || FALLBACK_ROLE_STYLE;
          return `
            <article class="paper-card rounded-xl p-5 sm:p-6 role-rail ${style.border}">
              <div class="flex items-center gap-2 mb-2">
                <span class="text-xs font-mono uppercase tracking-wide px-2 py-0.5 rounded-full ${style.chip}">
                  ${style.icon} ${escapeHtml(style.label)}
                </span>
              </div>
              <h3 class="font-display text-lg sm:text-xl mb-1.5">${escapeHtml(s.heading || style.label)}</h3>
              <div class="text-[15px] text-ink/85">${renderTextBlock(s.content)}</div>
            </article>`;
        })
        .join("")
    : `<p class="text-sm text-ink/50 italic">No sections were produced for this request.</p>`;

  const checklistHtml = checklist.length
    ? `<ul class="space-y-2.5">
        ${checklist
          .map(
            (item, i) => `
          <li class="checklist-item flex items-start gap-3">
            <input type="checkbox" id="chk-${i}" class="mt-1 w-4 h-4 accent-brassdark shrink-0">
            <label for="chk-${i}" class="text-[15px] leading-relaxed cursor-pointer">
              <span>${escapeHtml(item)}</span>
            </label>
          </li>`
          )
          .join("")}
      </ul>`
    : `<p class="text-sm text-ink/50 italic">No checklist items were produced.</p>`;

  tabReport.innerHTML = `
    <div class="paper-card rounded-2xl p-6 sm:p-9 mb-4">
      <div class="flex items-start justify-between flex-wrap gap-3 mb-4">
        <h2 class="font-display text-2xl sm:text-3xl leading-tight pr-4">${escapeHtml(report.title || "Business Plan Report")}</h2>
        ${docNote}
      </div>
      <blockquote class="border-l-4 border-brass pl-4 text-ink/75 italic text-[15px] sm:text-base leading-relaxed">
        ${escapeHtml(report.executive_summary || "")}
      </blockquote>
    </div>

    <div class="grid gap-4 mb-4">
      ${sectionsHtml}
    </div>

    <div class="paper-card rounded-2xl p-6 sm:p-8">
      <h3 class="font-display text-xl mb-4 flex items-center gap-2">
        <span class="text-brassdark">✓</span> Checklist &amp; next steps
      </h3>
      ${checklistHtml}
    </div>
  `;
}

function renderLogTab(record) {
  const steps = Array.isArray(record.steps) ? record.steps : [];

  const metaHtml = `
    <div class="paper-card rounded-2xl p-5 sm:p-6 mb-4 font-mono text-xs sm:text-[13px] text-ink/70 space-y-1">
      <div><span class="text-ink/45">run_id</span> · ${escapeHtml(record.run_id || record.job_id)}</div>
      <div><span class="text-ink/45">request</span> · ${escapeHtml(record.request)}</div>
      <div><span class="text-ink/45">document</span> · ${record.document_uploaded ? `uploaded (${record.document_chunk_count} chunks)` : "none"}</div>
    </div>
  `;

  const stepsHtml = steps.map((entry) => renderLogEntry(entry)).join("");

  tabLog.innerHTML = metaHtml + `<div class="space-y-3">${stepsHtml}</div>`;
}

function renderLogEntry(entry) {
  const style = ROLE_STYLES[entry.node] || FALLBACK_ROLE_STYLE;
  const label = ROLE_STYLES[entry.node] ? style.label : (entry.role || style.label);

  if (entry.skipped) {
    return `
      <details class="paper-card rounded-xl role-rail ${style.border} opacity-60">
        <summary class="flex items-center gap-3 px-5 py-3.5">
          <span class="text-xs font-mono px-2 py-0.5 rounded-full ${style.chip}">${style.icon} ${escapeHtml(label)}</span>
          <span class="text-xs font-mono text-ink/40">step ${entry.step}</span>
          <span class="ml-auto text-xs font-mono uppercase tracking-wide text-ink/40">Not selected</span>
        </summary>
        <div class="px-5 pb-4 text-sm text-ink/50 italic">${escapeHtml(entry.skip_reason || "Not selected by the orchestrator.")}</div>
      </details>`;
  }

  const verdict = entry.critic_verdict;
  const verdictBadge = verdict
    ? `<span class="text-xs font-mono uppercase tracking-wide px-2 py-0.5 rounded-full ${
        verdict.passed ? "bg-emerald-100 text-emerald-900" : "bg-red-100 text-red-900"
      }">
        ${verdict.passed ? "✓ pass" : "✕ fail"} · ${(verdict.confidence * 100).toFixed(0)}%
      </span>`
    : "";

  const retryBadge =
    entry.retry_info && entry.retry_info.is_retry
      ? `<span class="text-xs font-mono uppercase tracking-wide px-2 py-0.5 rounded-full bg-amber-100 text-amber-900">
          retry ${entry.retry_info.retry_number}/${entry.retry_info.max_retries}
        </span>`
      : "";

  const toolsHtml =
    entry.tool_calls && entry.tool_calls.length
      ? `
      <div class="mt-3">
        <div class="text-xs font-mono uppercase tracking-wide text-ink/45 mb-1.5">
          tools used — ${escapeHtml((entry.tools_used || []).join(", "))}
        </div>
        <div class="space-y-1.5">
          ${entry.tool_calls
            .map(
              (tc) => `
            <div class="font-mono text-[12px] bg-ink/5 rounded-lg px-3 py-2 overflow-x-auto">
              <span class="text-brassdark">${escapeHtml(tc.tool)}</span>(${escapeHtml(JSON.stringify(tc.args))})
              <div class="text-ink/50 mt-1">→ ${escapeHtml(tc.result_preview)}${tc.result_preview && tc.result_preview.length >= 300 ? "…" : ""}</div>
            </div>`
            )
            .join("")}
        </div>
      </div>`
      : "";

  return `
    <details class="paper-card rounded-xl role-rail ${style.border}" ${entry.node === "orchestrator" ? "open" : ""}>
      <summary class="flex items-center gap-3 px-5 py-3.5 flex-wrap">
        <span class="chevron text-ink/40 text-xs">▶</span>
        <span class="text-xs font-mono px-2 py-0.5 rounded-full ${style.chip}">${style.icon} ${escapeHtml(label)}</span>
        <span class="text-xs font-mono text-ink/40">step ${entry.step}</span>
        ${verdictBadge}
        ${retryBadge}
        <span class="ml-auto text-xs font-mono text-ink/35">${entry.duration_seconds}s</span>
      </summary>

      <div class="px-5 pb-5">
        ${
          entry.instructions_given
            ? `<div class="text-xs font-mono uppercase tracking-wide text-ink/45 mb-1">instruction</div>
               <p class="text-sm text-ink/75 mb-3 whitespace-pre-wrap">${escapeHtml(entry.instructions_given)}</p>`
            : ""
        }

        ${
          entry.node === "orchestrator" && entry.output
            ? `<div class="text-xs font-mono uppercase tracking-wide text-ink/45 mb-1">plan</div>
               <pre class="font-mono text-[12px] bg-ink/5 rounded-lg px-3 py-2 overflow-x-auto mb-3">${escapeHtml(JSON.stringify(entry.output, null, 2))}</pre>`
            : ""
        }

        ${
          entry.node === "synthesizer" && entry.output
            ? `<div class="text-xs font-mono uppercase tracking-wide text-ink/45 mb-1">final report object</div>
               <pre class="font-mono text-[12px] bg-ink/5 rounded-lg px-3 py-2 overflow-x-auto mb-3">${escapeHtml(JSON.stringify(entry.output, null, 2))}</pre>`
            : ""
        }

        ${
          entry.output && entry.node !== "orchestrator" && entry.node !== "synthesizer"
            ? `<div class="text-xs font-mono uppercase tracking-wide text-ink/45 mb-1">output</div>
               <div class="text-sm text-ink/85">${renderTextBlock(entry.output)}</div>`
            : ""
        }

        ${toolsHtml}

        ${
          verdict
            ? `<div class="mt-3 text-xs font-mono uppercase tracking-wide text-ink/45 mb-1">critic reasoning</div>
               <p class="text-sm text-ink/70 italic">${escapeHtml(verdict.reason)}</p>`
            : ""
        }
      </div>
    </details>`;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.setAttribute("aria-selected", "false"));
    btn.setAttribute("aria-selected", "true");

    const target = btn.dataset.tab;
    tabReport.classList.toggle("hidden", target !== "report");
    tabLog.classList.toggle("hidden", target !== "log");
  });
});