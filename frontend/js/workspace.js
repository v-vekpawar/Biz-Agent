(function () {
  const { h } = BZ;

  BZ.workspaceView = async (app, { id }) => {
    const ws = { id: Number(id), view: null, job: null, risks: [], recommended: null, sprint: null, sprints: [], selectedSprintId: null, docs: [], draftOnly: null, chosenHypothesis: null, review: null };
    const root = h("div", { class: "wrap" });
    app.append(root);
    let pollTimer = null, dead = false;

    async function load() {
      const base = "/business-cases/" + ws.id;
      const [c, ov, scan, risks, sprints, docs, review] = await Promise.all([
        BZ.api(base), BZ.api(base + "/overview"), BZ.api(base + "/scan"), BZ.api(base + "/risks"), BZ.api(base + "/sprints"),
        BZ.api(base + "/documents").catch(() => []),
        BZ.api(base + "/idea-review").catch(() => null),
      ]);
      Object.assign(ws, { case: c, overview: ov, job: scan.job, risks: risks.risks, recommended: risks.recommended_hypothesis_id, docs, sprints, review });
      const preferredId = ws.selectedSprintId || ov.current_sprint_id;
      ws.sprint = sprints.find((s) => s.id === preferredId) || null;
      if (ws.selectedSprintId && !ws.sprint) ws.selectedSprintId = null;
      if (ws.sprint && ws.sprint.locked_at) ws.draftOnly = null;
      if (!ws.view) ws.view = ov.stage === "decided" ? "decision" : ["test_draft", "testing"].includes(ov.stage) ? "test" : ov.stage === "idea" && !review ? "review" : "scan";
    }

    async function refresh() { await load(); if (!dead) draw(); }
    ws.render = draw;

    function rail() {
      const locked = ws.sprint && ws.sprint.locked_at, decided = !!(ws.sprint && ws.sprint.status === "concluded");
      const item = (view, label, done, disabled) => h("button", { class: done ? "done" : "", disabled, "aria-current": ws.view === view ? "step" : null,
        onclick: () => { ws.view = view; draw(); } }, h("span", { class: "pip" }, done ? "✓" : ""), label);
      return h("nav", { class: "rail", "aria-label": "Progress" },
        item("review", "Idea review", !!ws.review, false),
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
      const box = h("div");
      panel.append(box);
      (async () => {
        let d;
        try {
          d = await BZ.api("/business-cases/" + ws.id + "/decision");
        } catch (e) {
          BZ.clear(box).append(h("div", { class: "err" }, e.message));
          return;
        }
        const s = ws.sprint;
        const dl = h("button", { class: "btn" }, "Download decision brief (PDF)");
        dl.onclick = BZ.action(dl, downloadBrief);

        // verdict banner: the live sprint component when a test exists
        const banner = (s && s.locked_at && s.evaluation)
          ? BZ.verdictBanner(s.evaluation, s)
          : h("div", { class: "verdict " + (d.verdict.key === "none" ? "keep_running" : d.verdict.key) },
              h("div", { class: "word" }, d.verdict.label),
              h("p", { class: "why" }, d.verdict.detail),
              h("p", { class: "small", style: { margin: "6px 0 0" } }, h("b", {}, "Basis: "), d.verdict.basis));

        const PRI = { now: ["NOW", "pri-now"], next: ["NEXT", "pri-next"], later: ["LATER", "pri-later"] };
        const LEVEL = { critical: "Critical", open: "Open", thin: "Thin support", partial: "Partly supported", low: "Lower risk" };

        BZ.clear(box).append(
          banner,
          h("div", { class: "sheet" },
            h("h3", { style: { marginBottom: "4px" } }, "What you should do"),
            h("p", { class: "muted small" }, "Derived from your data — the verdict, the locked rule and the ranked risks. Not generic advice."),
            h("ol", { class: "decisions" }, d.decisions.map((x) => {
              const [label, cls] = PRI[x.priority] || PRI.later;
              return h("li", { class: "decision" },
                h("span", { class: "pri " + cls }, label),
                h("div", {},
                  h("div", { class: "decision-title" }, x.title),
                  h("p", { class: "muted small", style: { margin: "4px 0 0" } }, x.detail)));
            }))),
          d.sprint && d.sprint.evaluation ? h("div", { class: "sheet" },
            h("h3", { style: { marginBottom: "8px" } }, "The test behind this verdict"),
            h("p", { class: "small", style: { margin: "0 0 6px" } }, h("b", {}, "Claim: "), d.sprint.claim),
            d.sprint.evaluation.metrics.map(BZ.metricBlock),
            h("div", { class: "stats" },
              h("div", {}, h("span", {}, "Visitors"), h("b", {}, String(d.sprint.evaluation.counts.visitors))),
              h("div", {}, h("span", {}, "Signups"), h("b", {}, String(d.sprint.evaluation.counts.signups))),
              h("div", {}, h("span", {}, "Conversations"), h("b", {}, String(d.sprint.evaluation.counts.interviews))),
              h("div", {}, h("span", {}, "Committed"), h("b", {}, String(d.sprint.evaluation.counts.committed))))) : null,
          d.risks.length ? h("div", { class: "sheet" },
            h("h3", { style: { marginBottom: "8px" } }, "The risks behind it"),
            h("div", { class: "scroll" }, h("table", { class: "t" },
              h("thead", {}, h("tr", {}, h("th", {}, "Risk"), h("th", {}, "Level"), h("th", {}, "Evidence"))),
              h("tbody", {}, d.risks.map((r) => h("tr", {},
                h("td", {}, r.statement),
                h("td", {}, h("span", { class: "level " + r.level }, LEVEL[r.level] || r.level)),
                h("td", {}, r.evidence.supports + " for / " + r.evidence.contradicts + " against / " + r.evidence.verified + " verified"))))))) : null,
          h("div", { class: "sheet" },
            h("div", { class: "spread", style: { marginBottom: "8px" } },
              h("h3", {}, "Take it with you"),
              h("span", { class: "muted tiny" }, d.evidence.total + " sources: " + d.evidence.verified + " verified, " + (d.evidence.unverified + d.evidence.indeterminate + d.evidence.failed) + " not")),
            h("p", { class: "muted small" }, "The brief is a two-page PDF: the verdict, your decisions, the biggest risks, the locked test and its results, and the sources behind it. Generated when you click, never stored."),
            h("div", { class: "inline" }, dl,
              h("button", { class: "btn secondary", onclick: () => { ws.view = "test"; draw(); } }, "See the live data"),
              s && s.locked_at ? h("button", { class: "btn secondary", onclick: () => { ws.view = "test"; draw(); } }, "Open the test") : null)));
      })();
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

      if (ws.view === "review") BZ.reviewPanel(ws, panel, refresh);
      else if (ws.view === "scan") BZ.scanPanel(ws, panel, refresh);
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
