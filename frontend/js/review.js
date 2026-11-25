/* The pre-scan idea review: how strong is the idea as written? */
(function () {
  const { h } = BZ;

  const TIER = {
    strong: ["Strong write-up", "var(--go)", "var(--go-wash)"],
    promising: ["Promising", "var(--cobalt)", "var(--cobalt-wash)"],
    needs_work: ["Needs work", "var(--pivot)", "var(--pivot-wash)"],
    too_vague: ["Too vague to test", "var(--stop)", "var(--stop-wash)"],
  };
  const SUB = [["clarity", "Clarity"], ["customer", "Who it's for"], ["problem", "Problem"],
               ["differentiation", "Edge"], ["monetization", "Pricing"]];

  function ring(score, color) {
    const NS = "http://www.w3.org/2000/svg", R = 52, C = 2 * Math.PI * R;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 130 130");
    svg.setAttribute("class", "review-ring");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Idea readiness score " + score + " out of 100");
    const el = (name, attrs, text) => {
      const n = document.createElementNS(NS, name);
      for (const k in attrs) n.setAttribute(k, attrs[k]);
      if (text != null) n.textContent = text;
      svg.append(n);
      return n;
    };
    el("circle", { cx: 65, cy: 65, r: R, fill: "none", stroke: "rgba(33,29,26,.1)", "stroke-width": 11 });
    el("circle", {
      cx: 65, cy: 65, r: R, fill: "none", stroke: color, "stroke-width": 11,
      "stroke-linecap": "round", "stroke-dasharray": C, "stroke-dashoffset": C * (1 - score / 100),
      transform: "rotate(-90 65 65)",
    });
    el("text", { x: 65, y: 62, "text-anchor": "middle", "font-size": 34, "font-weight": 700, fill: "var(--ink)" }, String(score));
    el("text", { x: 65, y: 84, "text-anchor": "middle", "font-size": 11.5, fill: "var(--muted)" }, "out of 100");
    return svg;
  }

  function subScoreBars(scores) {
    if (!scores) return null;
    return h("div", { class: "review-subs" }, SUB.map(([key, label]) => {
      const v = Math.max(0, Math.min(10, Number(scores[key]) || 0));
      return h("div", { class: "review-sub" },
        h("span", { class: "review-sub-label" }, label),
        h("span", { class: "review-sub-track" }, h("i", { style: { width: v * 10 + "%" } })),
        h("span", { class: "review-sub-num" }, String(v)));
    }));
  }

  const listBlock = (title, items, cls) => items && items.length
    ? h("div", { class: "review-block " + (cls || "") }, h("h3", {}, title),
        h("ul", { class: "review-list" }, items.map((i) => h("li", {}, i))))
    : null;

  BZ.reviewPanel = (ws, panel, refresh) => {
    const runScan = () => { ws.view = "scan"; ws.render(); };

    if (!ws.review) {
      const btn = h("button", { class: "btn" }, "Analyze my idea");
      btn.onclick = BZ.action(btn, async () => {
        btn.textContent = "Reading your idea...";
        await BZ.api("/business-cases/" + ws.id + "/idea-review", { method: "POST" });
        await refresh();
      });
      panel.append(
        h("div", { class: "sheet" },
          h("h2", {}, "First: how strong is your idea?"),
          h("p", { class: "muted" }, "Before searching for evidence, Biz-Agent reads your write-up and tells you honestly how specific and testable it is: a readiness score, what's strong, what's weak, and what's missing."),
          h("p", { class: "muted small" }, "This is AI feedback on how well your idea is described — not market validation. The risk scan and your customer test are what actually test it."),
          h("div", { class: "inline", style: { marginTop: "10px" } }, btn,
            h("button", { class: "btn secondary", onclick: runScan }, "Skip to the risk scan"))));
      return;
    }

    const r = ws.review.result;
    const [tierLabel, tierColor, tierWash] = TIER[r.tier] || TIER.promising;
    const again = h("button", { class: "btn secondary" }, "Review again");
    again.onclick = BZ.action(again, async () => {
      again.textContent = "Reading your idea...";
      await BZ.api("/business-cases/" + ws.id + "/idea-review", { method: "POST" });
      await refresh();
    });
    const next = h("button", { class: "btn", onclick: runScan },
      ws.risks && ws.risks.length ? "See the risk scan" : "Next: run the risk scan");

    panel.append(
      h("div", { class: "spread", style: { marginBottom: "6px" } },
        h("h2", {}, "How strong is your idea?"),
        h("span", { class: "muted tiny" }, "Reviewed " + BZ.date(ws.review.updated_at))),
      h("div", { class: "sheet review-card" },
        h("div", { class: "review-head" },
          ring(r.score, tierColor),
          h("div", { class: "review-head-copy" },
            h("span", { class: "review-tier", style: { color: tierColor, background: tierWash } }, tierLabel),
            h("p", { class: "review-summary" }, r.summary))),
        subScoreBars(r.scores),
        h("div", { class: "review-cols" },
          listBlock("What's strong", r.strengths, "good"),
          listBlock("What's weak", r.weaknesses, "bad")),
        listBlock("Fill these gaps", r.missing_info),
        listBlock("Make it sharper", r.suggestions),
        (r.context_gaps || []).length ? h("p", { class: "tiny muted", style: { marginBottom: 0 } },
          "You didn't tell us: " + r.context_gaps.join(", ") + ".") : null,
        h("p", { class: "tiny muted" }, "AI feedback on how well your idea is described — not market validation."),
        h("div", { class: "inline", style: { marginTop: "8px" } }, next, again)));
  };
})();
