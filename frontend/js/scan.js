(function () {
  const { h } = BZ;
  const STEPS = [["assumptions", "Work out what has to be true"], ["research", "Search for evidence for and against"],
                 ["verify", "Check the sources"], ["assess", "Weigh the evidence"], ["rank", "Rank the risks"]];
  const LEVEL = { critical: "Critical", open: "Open", thin: "Thin support", partial: "Partly supported", low: "Lower risk" };

  function riskRow(r, onTest) {
    const e = r.evidence;
    return h("div", { class: "risk" },
      h("div", { class: "top" },
        h("span", { class: "level " + r.level }, h("span", { class: "dot" }), LEVEL[r.level]),
        h("div", {},
          h("div", { class: "st" }, r.statement),
          h("div", { class: "hd" }, r.headline),
          h("div", { class: "counts" }, BZ.pluralize(e.supports, "source") + " for, " + e.contradicts + " against, " + e.verified + " verified")),
        r.sprint_testable && onTest ? h("button", { class: "btn secondary small", onclick: () => onTest(r) }, "Test this") : null),
      (r.rationale || r.next_step) && h("details", {}, h("summary", {}, "Why this rating"),
        r.rationale && h("p", {}, r.rationale), r.next_step && h("p", {}, h("b", {}, "Suggested next step: "), r.next_step)));
  }

  BZ.scanPanel = (ws, panel, refresh) => {
    const job = ws.job;
    const running = job && (job.status === "queued" || job.status === "running");

    if (running) {
      const idx = Math.max(0, STEPS.findIndex((s) => s[0] === job.step));
      panel.append(h("div", { class: "sheet" },
        h("h2", {}, "Scanning your idea"),
        h("p", { class: "muted" }, "This usually takes one to three minutes. You can leave this page; the scan keeps running."),
        h("div", { class: "bar", role: "progressbar", "aria-valuenow": job.progress, "aria-valuemin": 0, "aria-valuemax": 100 }, h("i", { style: { width: job.progress + "%" } })),
        h("ul", { class: "steps" }, STEPS.map((s, i) => h("li", { class: i < idx ? "done" : i === idx ? "on" : "" }, i < idx ? "Done" : i === idx ? "Now" : "Next", ": ", s[1])))));
      return;
    }

    const failed = job && job.status === "failed";
    const risks = ws.risks;
    const startBtn = h("button", { class: "btn" }, risks.length ? "Run the scan again" : "Run the risk scan");
    startBtn.onclick = BZ.action(startBtn, async () => { await BZ.api("/business-cases/" + ws.id + "/scan", { method: "POST" }); await refresh(); });

    if (!risks.length) {
      const docs = ws.docs || [];
      panel.append(h("div", { class: "sheet" },
        h("h2", {}, failed ? "The last scan didn't finish" : "Find what could sink this idea"),
        failed && h("div", { class: "callout bad" }, job.error),
        h("p", {}, "Biz-Agent will list the assumptions your idea depends on, search for evidence on both sides, check the sources, and rank the risks."),
        h("p", { class: "muted small" }, "Desk research can show reasons an idea may fail. It can't show that people will sign up or pay. That comes from the customer test in the next step."),
        docs.length ? h("p", { class: "small" }, "Using your uploaded documents: " + docs.map((d) => d.original_filename || d.filename || "file").join(", ")) : null,
        startBtn));
      return;
    }

    const top = risks.find((r) => r.hypothesis_id === ws.recommended) || risks[0];
    const goTest = (r) => { ws.chosenHypothesis = r.hypothesis_id; ws.view = "test"; ws.render(); };
    const warnings = (job && job.warnings) || [];
    panel.append(
      h("div", { class: "spread", style: { marginBottom: "6px" } }, h("h2", {}, "What is most likely to sink this idea"), startBtn),
      h("p", { class: "muted" }, "Ranked by how badly the evidence goes against each assumption. A real test beats more reading."),
      failed && h("div", { class: "callout bad" }, "The latest scan failed: " + job.error + " The ranking below is from the previous scan."),
      warnings.length ? h("div", { class: "callout warn" }, h("b", {}, "Heads up"), h("ul", {}, warnings.map((w) => h("li", {}, w)))) : null,
      h("div", {}, risks.map((r) => riskRow(r, goTest))),
      h("div", { class: "sheet", style: { marginTop: "22px" } },
        h("h3", {}, "Next: test the riskiest assumption with real people"),
        h("p", { class: "muted" }, "“" + top.statement + "”"),
        h("button", { class: "btn", onclick: () => goTest(top) }, "Set up a customer test")));
  };
})();
