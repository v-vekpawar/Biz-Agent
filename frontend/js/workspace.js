(function () {
  const { h } = BZ;

  BZ.workspaceView = async (app, { id }) => {
    const ws = { id: Number(id), view: null, job: null, risks: [], recommended: null, sprint: null, sprints: [], selectedSprintId: null, docs: [], draftOnly: null, chosenHypothesis: null };
    const root = h("div", { class: "wrap" });
    app.append(root);
    let pollTimer = null, dead = false;

    async function load() {
      const base = "/business-cases/" + ws.id;
      const [c, ov, scan, risks, sprints, docs] = await Promise.all([
        BZ.api(base), BZ.api(base + "/overview"), BZ.api(base + "/scan"), BZ.api(base + "/risks"), BZ.api(base + "/sprints"),
        BZ.api(base + "/documents").catch(() => []),
      ]);
      Object.assign(ws, { case: c, overview: ov, job: scan.job, risks: risks.risks, recommended: risks.recommended_hypothesis_id, docs, sprints });
      const preferredId = ws.selectedSprintId || ov.current_sprint_id;
      ws.sprint = sprints.find((s) => s.id === preferredId) || null;
      if (ws.selectedSprintId && !ws.sprint) ws.selectedSprintId = null;
      if (ws.sprint && ws.sprint.locked_at) ws.draftOnly = null;
      if (!ws.view) ws.view = ov.stage === "decided" ? "decision" : ["test_draft", "testing"].includes(ov.stage) ? "test" : "scan";
    }

    async function refresh() { await load(); if (!dead) draw(); }
    ws.render = draw;

    function rail() {
      const locked = ws.sprint && ws.sprint.locked_at, decided = !!(ws.sprint && ws.sprint.status === "concluded");
      const item = (view, label, done, disabled) => h("button", { class: done ? "done" : "", disabled, "aria-current": ws.view === view ? "step" : null,
        onclick: () => { ws.view = view; draw(); } }, h("span", { class: "pip" }, done ? "✓" : ""), label);
      return h("nav", { class: "rail", "aria-label": "Progress" },
        item("scan", "Risk scan", ws.risks.length > 0, false),
        item("test", "Customer test", !!locked, false),
        item("decision", "Decision", decided, !locked));
    }

    function validationHub() {
      const hub = h("section", { class: "sheet validation-hub", style: { margin: "18px 0" } },
        h("div", { class: "spread", style: { alignItems: "center" } },
          h("div", {}, h("h3", { style: { margin: "0 0 3px" } }, "Validation Hub"),
            h("p", { class: "muted small", style: { margin: 0 } }, "Run independent experiments for different assumptions under this idea.")),
          h("button", { class: "btn small", onclick: () => {
            ws.selectedSprintId = null; ws.sprint = null; ws.draftOnly = null; ws.chosenHypothesis = null; draw();
          } }, "New experiment")));
      const counts = {
        running: ws.sprints.filter((s) => s.status === "running").length,
        drafts: ws.sprints.filter((s) => s.status === "draft").length,
        concluded: ws.sprints.filter((s) => s.status === "concluded").length,
      };
      hub.append(h("div", { class: "validation-summary" },
        h("span", {}, h("b", {}, String(ws.sprints.length)), " total"),
        h("span", {}, h("b", {}, String(counts.running)), " running"),
        h("span", {}, h("b", {}, String(counts.drafts)), " drafts"),
        h("span", {}, h("b", {}, String(counts.concluded)), " concluded")));
      const list = h("div", { class: "validation-list" });
      if (!ws.sprints.length) {
        list.append(h("p", { class: "muted small" }, "No experiments yet. Create one for your highest-risk assumption."));
      } else {
        ws.sprints.forEach((s, index) => {
          const primary = (s.protocol && s.protocol.metrics || []).find((m) => m.role === "primary");
          const label = s.status === "running" ? "Running" : s.status === "paused" ? "Paused" : s.status === "concluded" ? "Concluded" : "Draft";
          const active = ws.sprint && ws.sprint.id === s.id;
          const linkedRisk = ws.risks.find((r) => r.hypothesis_id === s.hypothesis_id);
          const row = h("button", { class: "validation-item" + (active ? " active" : ""), type: "button",
            onclick: () => { ws.selectedSprintId = s.id; ws.sprint = s; ws.draftOnly = null; ws.view = "test"; draw(); } },
            h("span", { class: "validation-index" }, String(ws.sprints.length - index).padStart(2, "0")),
            h("span", { class: "validation-copy" },
              h("strong", {}, (linkedRisk && linkedRisk.statement) || (s.protocol && s.protocol.claim) || (s.content && s.content.headline) || "Untitled experiment"),
              h("small", {}, (s.content && s.content.headline ? s.content.headline + " · " : "") + ((s.protocol && s.protocol.audience) || "Audience not set"))),
            h("span", { class: "validation-meta" }, h("b", {}, label),
              h("small", {}, primary ? Math.round(primary.success_rate * 100) + "% target" : "No target")));
          list.append(row);
        });
      }
      hub.append(list);
      return hub;
    }

    function decisionPanel(panel) {
      const s = ws.sprint;
      if (!s || !s.locked_at) { panel.append(h("div", { class: "sheet" }, h("p", {}, "Your decision comes from a customer test. Lock a test to start collecting real signals."))); return; }
      const dl = h("button", { class: "btn" }, "Download decision brief (PDF)");
      dl.onclick = BZ.action(dl, downloadBrief);
      panel.append(BZ.verdictBanner(s.evaluation, s),
        h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "8px" } }, "Take it with you"),
          h("p", { class: "muted small" }, "A two-page brief: the verdict, the biggest risks, the locked test and its results, and the sources behind it. It is generated when you click and isn't stored on the server."),
          h("div", { class: "inline" }, dl, h("button", { class: "btn secondary", onclick: () => { ws.view = "test"; draw(); } }, "See the live data"))));
    }

    async function downloadBrief() {
      const { blob, filename } = await BZ.api("/business-cases/" + ws.id + "/brief.pdf", { blob: true });
      BZ.save(blob, filename || "decision-brief.pdf");
    }

    function draw() {
      if (dead) return;
      const c = ws.case;
      BZ.clear(root);
      const dlBtn = h("button", { class: "btn secondary small" }, "Download decision brief");
      dlBtn.onclick = BZ.action(dlBtn, downloadBrief);
      const facts = [["For", c.target_customer], ["Price", c.pricing_model], ["Where", c.geography]].filter((f) => f[1]);
      root.append(
        h("div", { class: "crumb" }, h("a", { href: "#/" }, "Your ideas")),
        h("div", { class: "spread ws-head" }, h("h1", {}, c.title),
          h("div", { class: "inline" }, dlBtn,
            h("button", { class: "btn quiet small", onclick: () => BZ.confirm("Delete this idea?", "The idea, its research, any test and everything collected under it will be permanently deleted.", "Delete idea",
              async () => { await BZ.api("/business-cases/" + ws.id, { method: "DELETE" }); location.hash = "#/"; }, true) }, "Delete"))),
        h("p", { class: "ws-sub" }, c.idea_description),
        facts.length ? h("div", { class: "facts" }, facts.map(([k, v]) => h("span", {}, k + " ", h("b", {}, v)))) : null,
        rail());
      const panel = h("section", { "aria-live": "polite" });
      root.append(panel);

      if (ws.view === "scan") BZ.scanPanel(ws, panel, refresh);
      else if (ws.view === "decision") decisionPanel(panel);
      else {
        panel.append(validationHub());
        if (ws.sprint && ws.sprint.locked_at) BZ.livePanel(ws, panel, refresh);
        else if (ws.sprint || ws.draftOnly) BZ.draftEditor(ws, panel, refresh);
        else BZ.testChooser(ws, panel, refresh);
      }
      schedulePoll();
    }

    function schedulePoll() {
      clearTimeout(pollTimer);
      const scanning = ws.job && (ws.job.status === "queued" || ws.job.status === "running");
      const liveTest = ws.view === "test" && ws.sprint && ws.sprint.status === "running";
      if (!scanning && !liveTest) return;
      pollTimer = setTimeout(async () => {
        if (dead) return;
        try {
          if (scanning) {
            const out = await BZ.api("/business-cases/" + ws.id + "/scan");
            if (out.job && out.job.status !== ws.job.status || (out.job && out.job.progress !== ws.job.progress)) { ws.job = out.job; }
            if (!out.job || (out.job.status !== "queued" && out.job.status !== "running")) return refresh();
            draw();
          } else {
            const t = document.activeElement && document.activeElement.tagName;
            if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT") return schedulePoll();
            await refresh();
          }
        } catch (_) { schedulePoll(); }
      }, scanning ? 2500 : 30000);
    }

    await load();
    draw();
    return () => { dead = true; clearTimeout(pollTimer); };
  };
})();
