(function () {
  const { h } = BZ;

  const STAGE = {
    idea: ["Not scanned yet", ""], scanning: ["Scanning", "live"], scanned: ["Scanned, not tested", ""],
    test_draft: ["Test drafted", ""], testing: ["Test running", "live"], decided: ["Decided", ""],
  };
  BZ.stageLabel = (ov) => {
    if (ov.stage === "decided" && ov.verdict) return [BZ.VERDICT[ov.verdict], ov.verdict];
    return STAGE[ov.stage] || ["", ""];
  };

  BZ.ideasView = async (app) => {
    const head = h("div", { class: "pagehead" }, h("h1", {}, "Your ideas"),
      h("a", { class: "btn", href: "#/new" }, "Add an idea"));
    const list = h("div", { class: "ideas", "aria-busy": "true" });
    app.append(h("div", { class: "wrap" }, head, list));

    const cases = await BZ.api("/business-cases");
    const overviews = await Promise.all(cases.map((c) => BZ.api("/business-cases/" + c.id + "/overview").catch(() => ({ stage: "idea" }))));
    list.removeAttribute("aria-busy");
    if (!cases.length) {
      list.replaceWith(h("div", { class: "empty" },
        h("h2", {}, "Start with one idea"),
        h("p", { class: "muted" }, "Describe it in a few sentences. Biz-Agent will find what is most likely to sink it, then help you test the riskiest part with real people."),
        h("a", { class: "btn", href: "#/new" }, "Add your first idea")));
      return;
    }
    cases.forEach((c, i) => {
      const [label, tone] = BZ.stageLabel(overviews[i]);
      list.append(h("a", { class: "idea", href: "#/idea/" + c.id },
        h("span", { class: "t" }, c.title),
        h("span", { class: "stagechip" }, h("span", { class: "dot " + tone }), label),
        h("span", { class: "d" }, c.idea_description)));
    });
  };

  BZ.newIdeaView = (app) => {
    const f = {};
    const field = (id, label, el, hint) => h("div", { class: "field" }, h("label", { for: id }, label), el, hint && h("div", { class: "hint" }, hint));
    const inp = (id, ph, max) => (f[id] = h("input", { id, type: "text", placeholder: ph || "", maxLength: max || 200 }));
    const area = (id, ph, rows) => (f[id] = h("textarea", { id, placeholder: ph || "", rows: rows || 3 }));
    const err = h("div", { class: "err", role: "alert" });
    const files = h("input", { id: "docs", type: "file", multiple: true, accept: ".pdf,.docx,.xlsx,.txt,.md,.csv" });
    const submit = h("button", { class: "btn", type: "submit" }, "Save and continue");

    const form = h("form", { novalidate: true, onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      const get = (k) => f[k].value.trim() || undefined;
      if (!get("title") || !get("idea_description")) { err.textContent = "Give your idea a name and describe it in a sentence or two."; return; }
      submit.disabled = true;
      try {
        const c = await BZ.api("/business-cases", { method: "POST", body: {
          title: get("title"), idea_description: get("idea_description"), target_customer: get("target_customer"),
          customer_problem: get("customer_problem"), pricing_model: get("pricing_model"), geography: get("geography"),
          known_competitors: get("known_competitors") } });
        for (const file of files.files) {
          const fd = new FormData(); fd.append("file", file);
          try { await BZ.api("/business-cases/" + c.id + "/documents", { method: "POST", body: fd }); }
          catch (ex) { BZ.toast(file.name + ": " + ex.message, true); }
        }
        location.hash = "#/idea/" + c.id;
      } catch (ex) { err.textContent = ex.message; submit.disabled = false; }
    } },
      field("title", "Name", inp("title", "e.g. Small-batch chai subscription", 200)),
      field("idea_description", "What is it?", area("idea_description", "Say what you would sell, to whom, and why they would care.", 4)),
      h("div", { class: "row" },
        field("target_customer", "Who is it for?", inp("target_customer", "e.g. Office workers in Pune")),
        field("pricing_model", "Price", inp("pricing_model", "e.g. INR 499 per month"))),
      field("customer_problem", "The problem it solves", area("customer_problem", "What do these people struggle with today?", 2)),
      h("div", { class: "row" },
        field("geography", "Where", inp("geography", "e.g. Pune, India")),
        field("known_competitors", "Alternatives they use now", inp("known_competitors", "Competitors, workarounds, doing nothing", 300))),
      field("docs", "Documents (optional)", files, "Business plan, survey results or research notes. PDF, Word, Excel, text. Up to 10 MB each."),
      err, h("div", { class: "inline" }, submit, h("a", { class: "btn secondary", href: "#/" }, "Cancel")));

    app.append(h("div", { class: "wrap narrow" }, h("h1", { style: { marginBottom: "22px" } }, "Add an idea"),
      h("div", { class: "sheet" }, form),
      h("p", { class: "hint", style: { marginTop: "14px" } }, "The more specific you are about who it is for and what it costs, the sharper the risk scan.")));
    f.title.focus();
  };
})();
