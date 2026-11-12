(function () {
  const { h } = BZ;
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d); };

  function defaults(ws) {
    const c = ws.case, u = BZ.user() || {};
    const audience = c.target_customer || "People who have this problem";
    return {
      content: { headline: c.title, subheadline: "", bullets: [""], cta_label: "Join the waitlist", extra_question: "", price_hint: c.pricing_model || "",
        visual_theme: "paper_brass", visual_style: "editorial", hero_kicker: c.title.toUpperCase().slice(0, 70),
        creator_name: u.display_name || "", contact_email: u.email || "" },
      protocol: { claim: "At least 10% of " + audience + " who see this page will join the waitlist.", audience, traffic_plan: "",
        confidence: 0.9, deadline: addDays(14),
        metrics: [{ key: "waitlist_conversion", role: "primary", success_rate: 0.10, failure_rate: 0.03, min_sample: 100 }] },
    };
  }

  /** Chooser shown when no sprint exists yet. */
  BZ.testChooser = (ws, panel, refresh) => {
    const risks = ws.risks;
    const testable = risks.filter((r) => r.sprint_testable);
    const sel = h("select", { id: "hyp" },
      h("option", { value: "" }, "None in particular: let me write the claim"),
      (testable.length ? testable : risks).map((r) => h("option", { value: r.hypothesis_id, selected: r.hypothesis_id === (ws.chosenHypothesis || ws.recommended) }, r.statement.slice(0, 110))));
    const aiBtn = h("button", { class: "btn" }, "Generate a test kit with AI");
    aiBtn.onclick = BZ.action(aiBtn, async () => {
      aiBtn.textContent = "Generating...";
      const body = sel.value ? { hypothesis_id: Number(sel.value) } : {};
      const s = await BZ.api("/business-cases/" + ws.id + "/sprints/ai-draft", { method: "POST", body });
      ws.sprint = s; ws.selectedSprintId = s.id; ws.chosenHypothesis = null; await refresh();
    });
    const manual = h("button", { class: "btn secondary", onclick: () => { ws.draftOnly = { hypothesis_id: sel.value ? Number(sel.value) : null, ...defaults(ws) }; ws.render(); } }, "Write it myself");
    panel.append(h("div", { class: "sheet" },
      h("h2", {}, "Set up a customer test"),
      h("p", {}, "You will get a public page, a pass/fail rule that you lock before any data arrives, and an interview script. Real people's responses decide the verdict."),
      h("div", { class: "field" }, h("label", { for: "hyp" }, "What are you testing?"), sel,
        h("div", { class: "hint" }, "Pick the assumption you are most afraid is wrong. Only assumptions a landing page or interview can test are listed.")),
      h("div", { class: "inline" }, aiBtn, manual)));
  };

  /** The draft editor. `sprint` is null for an unsaved manual draft (ws.draftOnly). */
  BZ.draftEditor = (ws, panel, refresh) => {
    const sprint = ws.sprint;
    const init = sprint ? { content: sprint.content, protocol: sprint.protocol } : ws.draftOnly;
    const c0 = init.content, p0 = init.protocol;
    const primary = p0.metrics.find((m) => m.role === "primary") || p0.metrics[0];
    const support = p0.metrics.find((m) => m.role === "supporting");
    let tab = "setup";
    const body = h("div");

    const f = {};
    const field = (id, label, el, hint) => h("div", { class: "field" }, h("label", { for: id }, label), el, hint && h("div", { class: "hint" }, hint));
    const txt = (id, v, max, ph) => (f[id] = h("input", { id, type: "text", value: v || "", maxLength: max, placeholder: ph || "" }));
    const area = (id, v, rows, max) => (f[id] = h("textarea", { id, value: v || "", rows, maxLength: max }));
    const num = (id, v, step, min, max) => (f[id] = h("input", { id, type: "number", value: v, step, min, max, inputMode: "decimal" }));
    const pctVal = (x) => Math.round(x * 1000) / 10;

    f.claim = area("claim", p0.claim, 2, 300);
    f.audience = txt("audience", p0.audience, 200);
    f.traffic = txt("traffic", p0.traffic_plan, 300, "e.g. 3 Pune coworking Slack groups, my LinkedIn network");
    f.headline = txt("headline", c0.headline, 120);
    f.sub = txt("sub", c0.subheadline, 240);
    f.bullets = area("bullets", (c0.bullets || []).join("\n"), 4, 760);
    f.cta = txt("cta", c0.cta_label, 30);
    f.q = txt("q", c0.extra_question, 140, "e.g. What do you use today?");
    f.price = txt("price", c0.price_hint, 80, "Optional. Leave empty to show no price.");
    f.kicker = txt("kicker", c0.hero_kicker, 70, "Short category / product label");
    const themeOptions = [
      ["fresh_green", "Fresh green · food, wellness, sustainability"],
      ["midnight_blue", "Midnight blue · professional, finance, productivity"],
      ["warm_citrus", "Warm citrus · food, lifestyle, consumer products"],
      ["violet_tech", "Violet tech · software, AI, education"],
      ["earth_clay", "Earth clay · craft, local services, ethical products"],
      ["rose_editorial", "Rose editorial · beauty, fashion, creator brands"],
      ["paper_brass", "Paper & brass · neutral editorial"]
    ];
    f.theme = h("select", { id: "visual-theme" }, themeOptions.map(([v, label]) => h("option", { value: v, selected: (c0.visual_theme || "paper_brass") === v }, label)));
    f.style = h("select", { id: "visual-style" }, ["editorial", "bold", "minimal", "playful"].map((v) => h("option", { value: v, selected: (c0.visual_style || "editorial") === v }, v[0].toUpperCase() + v.slice(1))));
    f.creator = txt("creator", c0.creator_name, 80);
    f.contact = h("input", { id: "contact", type: "email", value: c0.contact_email || "", maxLength: 254 });
    f.s1 = num("s1", pctVal(primary.success_rate), 0.5, 0.5, 90);
    f.f1 = num("f1", pctVal(primary.failure_rate), 0.5, 0.1, 89);
    f.n1 = num("n1", primary.min_sample, 10, 30, 100000);
    f.conf = h("select", { id: "conf" }, [0.8, 0.9, 0.95].map((v) => h("option", { value: v, selected: Math.abs(v - p0.confidence) < 1e-6 }, Math.round(v * 100) + "%")));
    f.deadline = h("input", { id: "deadline", type: "date", value: p0.deadline, min: addDays(1), max: addDays(90) });
    f.useSupport = h("input", { id: "usesup", type: "checkbox", checked: !!support });
    f.s2 = num("s2", support ? pctVal(support.success_rate) : 30, 1, 5, 95);
    f.f2 = num("f2", support ? pctVal(support.failure_rate) : 10, 1, 1, 94);
    f.n2 = num("n2", support ? support.min_sample : 10, 1, 5, 1000);
    const supBox = h("div", { class: "row3", style: { marginTop: "12px" } },
      field("s2", "Target (%)", f.s2), field("f2", "Floor (%)", f.f2), field("n2", "Minimum conversations", f.n2));
    const syncSup = () => supBox.classList.toggle("hidden", !f.useSupport.checked);
    f.useSupport.onchange = syncSup; syncSup();

    const hintEl = h("div", { class: "hint", id: "samplehint" });
    let hintTimer;
    const updateHint = () => {
      clearTimeout(hintTimer);
      hintTimer = setTimeout(async () => {
        const s = Number(f.s1.value) / 100;
        if (!(s > 0 && s < 1)) return;
        try {
          const out = await BZ.api("/stats/plan", { method: "POST", body: { success_rate: s, confidence: Number(f.conf.value) } });
          hintEl.textContent = "To be able to call a go at a " + f.s1.value + "% target, plan for about " + out.suggested_min_sample + " visitors.";
          hintEl.dataset.n = out.suggested_min_sample;
        } catch (_) {}
      }, 350);
    };
    f.s1.addEventListener("input", updateHint); f.conf.addEventListener("change", updateHint); updateHint();

    function collect() {
      const metrics = [{ key: "waitlist_conversion", role: "primary", success_rate: Number(f.s1.value) / 100, failure_rate: Number(f.f1.value) / 100, min_sample: Number(f.n1.value) }];
      if (f.useSupport.checked) metrics.push({ key: "interview_commitment", role: "supporting", success_rate: Number(f.s2.value) / 100, failure_rate: Number(f.f2.value) / 100, min_sample: Number(f.n2.value) });
      const nz = (v) => (v.trim() ? v.trim() : null);
      return {
        content: { headline: f.headline.value.trim(), subheadline: nz(f.sub.value), bullets: f.bullets.value.split("\n").map((l) => l.trim()).filter(Boolean),
          cta_label: f.cta.value.trim() || "Join the waitlist", extra_question: nz(f.q.value), price_hint: nz(f.price.value),
          visual_theme: f.theme.value, visual_style: f.style.value, hero_kicker: nz(f.kicker.value),
          creator_name: f.creator.value.trim(), contact_email: f.contact.value.trim() },
        protocol: { claim: f.claim.value.trim(), audience: f.audience.value.trim(), traffic_plan: nz(f.traffic.value), confidence: Number(f.conf.value),
          deadline: f.deadline.value, metrics },
      };
    }

    async function save() {
      const payload = collect();
      if (ws.sprint) { ws.sprint = await BZ.api("/sprints/" + ws.sprint.id, { method: "PATCH", body: payload }); }
      else {
        ws.sprint = await BZ.api("/business-cases/" + ws.id + "/sprints", { method: "POST", body: { ...payload, hypothesis_id: ws.draftOnly.hypothesis_id } });
        ws.selectedSprintId = ws.sprint.id;
        ws.draftOnly = null;
      }
      return ws.sprint;
    }

    const err = h("div", { class: "err", role: "alert" });
    const saveBtn = h("button", { class: "btn secondary" }, "Save draft");
    saveBtn.onclick = BZ.action(saveBtn, async () => { err.textContent = ""; try { await save(); BZ.toast("Draft saved"); await refresh(); } catch (e) { err.textContent = e.message; } });
    const lockBtn = h("button", { class: "btn" }, "Review and lock");
    lockBtn.onclick = BZ.action(lockBtn, async () => {
      err.textContent = "";
      let s; try { s = await save(); } catch (e) { err.textContent = e.message; return; }
      openLock(ws, s, refresh);
    });

    const setupTab = () => h("div", {},
      h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "12px" } }, "What you are claiming"),
        field("claim", "The claim, in one sentence", f.claim, "It has to be falsifiable. The test either supports it or it doesn't."),
        field("audience", "Who should see the page", f.audience),
        field("traffic", "How will people find the page?", f.traffic, "A page nobody visits teaches nothing. Name where you will send people.")),
      h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "4px" } }, "The decision rule"),
        h("p", { class: "muted small" }, "Set these before you see any data. After you lock, they can't change."),
        h("div", { class: "row3" }, field("s1", "Target: % of visitors who join", f.s1, "At or above this is a go."), field("f1", "Floor (%)", f.f1, "Credibly below this is a stop."),
          field("n1", "Minimum visitors", f.n1, "No call is made before this.")),
        hintEl,
        h("div", { class: "row", style: { marginTop: "14px" } }, field("conf", "Confidence", f.conf, "How sure the range must be before the rule calls it."), field("deadline", "Deadline", f.deadline, "End of day, UTC. At most 90 days out.")),
        h("label", { class: "check", style: { marginTop: "6px" } }, f.useSupport, "Also track interview commitment (supporting metric)"),
        supBox,
        h("div", { class: "hint" }, "A commitment is something concrete: a pre-order, a paid pilot, a booked follow-up. Polite interest doesn't count.")),
      h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "12px" } }, "What the public page says"),
        field("headline", "Headline", f.headline), field("sub", "Subheadline (optional)", f.sub),
        field("bullets", "What the customer gets (one per line, up to 5)", f.bullets),
        h("div", { class: "row" }, field("cta", "Button text", f.cta), field("q", "One optional question for visitors", f.q)),
        field("price", "Price shown", f.price, "Only show a price you are really considering."),
        field("kicker", "Small category label", f.kicker, "For example: HEALTHY HOSTEL SNACKS."),
        h("div", { class: "row" }, field("visual-theme", "Visual palette", f.theme), field("visual-style", "Layout style", f.style)),
        h("div", { class: "row" }, field("creator", "Your name (public)", f.creator), field("contact", "Contact email (public)", f.contact, "Visitors use this to ask you to delete their data."))));

    const previewTab = () => {
      const box = h("div", {}, h("p", { class: "muted" }, "Loading preview..."));
      (async () => {
        try {
          const s = await save();
          const html = await BZ.api("/sprints/" + s.id + "/preview", { text: true });
          BZ.clear(box).append(h("p", { class: "muted small" }, "This is exactly what visitors will see. Your draft was saved."),
            h("iframe", { class: "preview", sandbox: "", srcdoc: html, title: "Page preview" }));
        } catch (e) { BZ.clear(box).append(h("div", { class: "err" }, e.message)); }
      })();
      return box;
    };

    const kitTab = () => {
      const k = (ws.sprint && ws.sprint.kit) || null;
      if (!k) return h("div", { class: "sheet" }, h("p", { class: "muted" }, "No test kit yet. Generate a draft with AI from the previous step to get an interview script and outreach messages, or write your own."));
      const list = (items) => h("ol", { class: "kitlist" }, items.map((i) => h("li", {}, i)));
      return h("div", {},
        k.threshold_rationale && h("div", { class: "callout" }, h("b", {}, "Why these thresholds: "), k.threshold_rationale, " They are assumptions. Change them if they don't fit your situation."),
        h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "8px" } }, "Interview script"), list(k.interview_script || [])),
        h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "8px" } }, "Outreach messages"),
          (k.outreach || []).map((o) => h("div", { style: { marginBottom: "14px" } }, h("b", {}, o.channel), h("p", { class: "small", style: { margin: "4px 0 6px" } }, o.message),
            h("button", { class: "btn quiet small", onclick: () => BZ.copy(o.message) }, "Copy")))),
        (k.where_to_find_them || []).length ? h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "8px" } }, "Where to find them"), h("ul", { class: "kitlist" }, k.where_to_find_them.map((i) => h("li", {}, i)))) : null);
    };

    const tabs = h("div", { class: "tabs", role: "tablist" });
    const draw = () => {
      BZ.clear(tabs).append([["setup", "Setup"], ["preview", "Preview page"], ["kit", "Test kit"]].map(([id, label]) =>
        h("button", { role: "tab", "aria-selected": tab === id, onclick: () => { tab = id; draw(); } }, label)));
      BZ.clear(body).append(tab === "setup" ? setupTab() : tab === "preview" ? previewTab() : kitTab());
    };
    draw();

    panel.append(
      h("div", { class: "spread", style: { marginBottom: "12px" } }, h("h2", {}, "Design the test"),
        sprint && sprint.source === "ai" ? h("span", { class: "muted small" }, "AI draft. Read it critically and edit anything.") : null),
      sprint && sprint.source === "ai" ? h("div", { class: "callout" }, "The AI proposed the page, the wording and the thresholds. Sample sizes come from a statistical formula, not the model. Nothing is public until you lock the test.") : null,
      tabs, body, err,
      h("div", { class: "inline", style: { marginTop: "6px" } }, lockBtn, saveBtn,
        h("button", { class: "btn quiet", onclick: () => BZ.confirm("Delete this draft?", "The draft will be removed.", "Delete draft", async () => {
          if (ws.sprint) await BZ.api("/sprints/" + ws.sprint.id, { method: "DELETE" });
          ws.sprint = null; ws.draftOnly = null; await refresh();
        }, true) }, "Delete draft")));
  };

  function openLock(ws, s, refresh) {
    const a = h("input", { type: "checkbox", id: "ack1" }), b = h("input", { type: "checkbox", id: "ack2" });
    const err = h("div", { class: "err", role: "alert" });
    BZ.modal({
      title: "Lock and launch this test",
      body: h("div", {},
        h("p", {}, "Locking pre-registers your claim and decision rule. That is what makes the verdict trustworthy."),
        h("p", { class: "small" }, "Target ", h("b", {}, BZ.pct(s.protocol.metrics[0].success_rate)), ", floor ", h("b", {}, BZ.pct(s.protocol.metrics[0].failure_rate)),
          ", at least ", h("b", {}, String(s.protocol.metrics[0].min_sample)), " visitors, ends ", h("b", {}, BZ.day(s.protocol.deadline)), "."),
        h("label", { class: "check", style: { margin: "14px 0 10px" } }, a, "The page will be public, with my name (" + s.content.creator_name + ") and contact email (" + s.content.contact_email + ") on it, and visitors' emails will be stored."),
        h("label", { class: "check" }, b, "I understand the page and the decision rule can't be edited after locking."), err),
      actions: (close) => [h("button", { class: "btn secondary", onclick: close }, "Not yet"),
        h("button", { class: "btn", onclick: async (e) => {
          const btn = e.currentTarget; err.textContent = ""; btn.disabled = true;
          try { ws.sprint = await BZ.api("/sprints/" + s.id + "/lock", { method: "POST", body: { acknowledge_public_page: a.checked, acknowledge_frozen: b.checked } }); close(); BZ.toast("Locked. Your page is live."); await refresh(); }
          catch (ex) { err.textContent = ex.message; btn.disabled = false; }
        } }, "Lock and go live")],
    });
  }
})();
