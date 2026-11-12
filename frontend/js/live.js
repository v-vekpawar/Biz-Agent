(function () {
  const { h } = BZ;
  const OUTCOME = { committed: "Committed", interested: "Interested", no: "Said no" };

  function verdictBanner(ev, s) {
    const finalSnap = s.verdicts && s.verdicts.length;
    const status = s.status === "concluded" ? "Concluded " + BZ.date(s.concluded_at)
      : s.status === "paused" ? "Paused: the page isn't collecting responses."
      : ev.finished ? "The window has closed. Conclude the test to record the result."
      : ev.days_left !== null ? BZ.pluralize(ev.days_left, "day") + " left (until " + BZ.day(ev.deadline) + ")." : "";
    return h("div", { class: "verdict " + ev.verdict },
      h("div", { class: "word" }, BZ.VERDICT[ev.verdict]),
      h("div", { class: "small", style: { marginTop: "4px" } }, finalSnap ? "Final result. " + status : "Live reading. " + status),
      h("p", { class: "why" }, ev.next_step),
      (ev.notes || []).map((n) => h("p", { class: "small", style: { margin: "6px 0 0" } }, n)));
  }

  BZ.verdictBanner = verdictBanner;

  function metricBlock(m) {
    return h("div", { class: "metric" },
      h("div", { class: "mh" }, h("div", {}, h("b", {}, m.label), h("span", { class: "muted small" }, m.role === "primary" ? "  decides the verdict" : "  supporting")),
        h("span", { class: "pill " + m.verdict }, BZ.VERDICT[m.verdict])),
      h("div", { class: "inline", style: { margin: "6px 0 2px" } }, h("span", { class: "big" }, BZ.pct(m.rate)),
        h("span", { class: "muted" }, m.successes + " of " + m.trials + " " + m.trial_unit)),
      BZ.ruler(m),
      h("p", { class: "small muted", style: { margin: "4px 0 0" } }, m.reason + " Range at " + Math.round(m.confidence * 100) + "% confidence. Minimum before any call: " + m.min_sample + "."));
  }

  BZ.livePanel = (ws, panel, refresh) => {
    const s = ws.sprint, ev = s.evaluation;
    const open = s.status === "running" || s.status === "paused";
    const signupsBox = h("div", { class: "scroll" }), signalsBox = h("div", { class: "scroll" });

    // share link
    const link = s.links.public_page || "";
    const linkRow = h("div", { class: "copy" }, h("input", { readOnly: true, value: link, "aria-label": "Public page link" }),
      h("button", { class: "btn secondary", onclick: () => BZ.copy(link) }, "Copy"),
      h("a", { class: "btn secondary", href: link, target: "_blank", rel: "noopener" }, "Open"));

    // channels
    const ch = s.channels || [];
    const channelTable = ch.length ? h("div", { class: "scroll" }, h("table", { class: "t" },
      h("thead", {}, h("tr", {}, h("th", {}, "Source"), h("th", {}, "Visitors"), h("th", {}, "Signups"))),
      h("tbody", {}, ch.map((c) => h("tr", {}, h("td", {}, c.channel), h("td", {}, c.visitors), h("td", {}, c.signups)))))) : null;

    // conversation log
    const outcome = h("select", { id: "oc", "aria-label": "Outcome" }, Object.entries(OUTCOME).map(([v, l]) => h("option", { value: v }, l)));
    const who = h("input", { id: "who", type: "text", maxLength: 200, placeholder: "Who (optional)" });
    const notes = h("input", { id: "nt", type: "text", maxLength: 2000, placeholder: "Notes (optional)" });
    const logBtn = h("button", { class: "btn small" }, "Add");
    logBtn.onclick = BZ.action(logBtn, async () => {
      await BZ.api("/sprints/" + s.id + "/signals", { method: "POST", body: { outcome: outcome.value, who: who.value, notes: notes.value } });
      await refresh();
    });

    const excludeModal = (title, url) => {
      const reason = h("input", { type: "text", maxLength: 300, placeholder: "Reason (shown publicly in the dossier)" });
      const err = h("div", { class: "err" });
      BZ.modal({ title, body: h("div", {}, h("p", { class: "small muted" }, "Excluded entries are removed from the counts, never deleted, and are always disclosed."), reason, err),
        actions: (close) => [h("button", { class: "btn secondary", onclick: close }, "Cancel"),
          h("button", { class: "btn danger", onclick: async (e) => { const btn = e.currentTarget; btn.disabled = true; try { await BZ.api(url, { method: "POST", body: { reason: reason.value } }); close(); await refresh(); } catch (x) { err.textContent = x.message; btn.disabled = false; } } }, "Exclude")] });
    };

    const loadLists = async () => {
      const [signups, signals] = await Promise.all([BZ.api("/sprints/" + s.id + "/signups"), BZ.api("/sprints/" + s.id + "/signals")]);
      BZ.clear(signupsBox).append(signups.length ? h("table", { class: "t" },
        h("thead", {}, h("tr", {}, h("th", {}, "Email"), h("th", {}, "Answer"), h("th", {}, "Source"), h("th", {}, "When"), h("th", {}, ""))),
        h("tbody", {}, signups.map((r) => h("tr", { class: r.excluded ? "excluded" : "" }, h("td", {}, r.email), h("td", {}, r.answer || ""), h("td", {}, r.channel || "direct"), h("td", {}, BZ.date(r.created_at)),
          h("td", {}, r.excluded ? h("span", { class: "muted tiny" }, "excluded: " + r.excluded_reason) : (open ? h("button", { class: "btn quiet small", onclick: () => excludeModal("Exclude this signup", "/sprints/" + s.id + "/signups/" + r.id + "/exclude") }, "Exclude") : null))))))
        : h("p", { class: "muted small" }, "No signups yet."));
      BZ.clear(signalsBox).append(signals.length ? h("table", { class: "t" },
        h("thead", {}, h("tr", {}, h("th", {}, "Outcome"), h("th", {}, "Who"), h("th", {}, "Notes"), h("th", {}, ""))),
        h("tbody", {}, signals.map((r) => h("tr", { class: r.excluded ? "excluded" : "" }, h("td", {}, OUTCOME[r.outcome]), h("td", {}, r.who || ""), h("td", {}, r.notes || ""),
          h("td", {}, r.excluded ? h("span", { class: "muted tiny" }, "excluded: " + r.excluded_reason) : (open ? h("button", { class: "btn quiet small", onclick: () => excludeModal("Exclude this entry", "/sprints/" + s.id + "/signals/" + r.id + "/exclude") }, "Exclude") : null))))))
        : h("p", { class: "muted small" }, "No conversations logged yet."));
    };
    loadLists().catch((e) => BZ.toast(e.message, true));

    // controls
    const pauseBtn = h("button", { class: "btn secondary" }, s.status === "paused" ? "Resume collecting" : "Pause collecting");
    pauseBtn.onclick = BZ.action(pauseBtn, async () => { ws.sprint = await BZ.api("/sprints/" + s.id + (s.status === "paused" ? "/resume" : "/pause"), { method: "POST" }); await refresh(); });

    const concludeBtn = h("button", { class: "btn" }, "Conclude the test");
    concludeBtn.onclick = () => {
      const early = ev.verdict === "keep_running";
      BZ.confirm(early ? "End the test early?" : "Record the result?",
        early ? "There isn't enough data for the rule to call this. Ending now records the result as inconclusive, and the page stops collecting."
          : "This records the verdict as final and stops the page collecting responses. You can't undo it.",
        early ? "End early" : "Record result", async () => { ws.sprint = await BZ.api("/sprints/" + s.id + "/conclude", { method: "POST", body: { force: early } }); await refresh(); });
    };

    const csvBtn = h("button", { class: "btn secondary small" }, "Export signups (CSV)");
    csvBtn.onclick = BZ.action(csvBtn, async () => { const { blob, filename } = await BZ.api("/sprints/" + s.id + "/signups.csv", { blob: true }); BZ.save(blob, filename || "signups.csv"); });

    // dossier
    const dossier = s.links.dossier;
    const dossierToggle = h("button", { class: "btn secondary small" }, s.dossier_enabled ? "Turn sharing off" : "Create a shareable dossier");
    dossierToggle.onclick = BZ.action(dossierToggle, async () => { ws.sprint = await BZ.api("/sprints/" + s.id + "/dossier", { method: "POST", body: { enabled: !s.dossier_enabled } }); await refresh(); });
    const rotate = h("button", { class: "btn quiet small" }, "Replace link");
    rotate.onclick = BZ.action(rotate, async () => { ws.sprint = await BZ.api("/sprints/" + s.id + "/rotate-dossier-link", { method: "POST" }); BZ.toast("Old link no longer works"); await refresh(); });

    panel.append(
      verdictBanner(ev, s),
      h("div", { class: "sheet" }, ev.metrics.map(metricBlock),
        h("div", { class: "stats" },
          h("div", {}, h("span", {}, "Visitors"), h("b", {}, ev.counts.visitors)), h("div", {}, h("span", {}, "Signups"), h("b", {}, ev.counts.signups)),
          h("div", {}, h("span", {}, "Conversations"), h("b", {}, ev.counts.interviews)), h("div", {}, h("span", {}, "Committed"), h("b", {}, ev.counts.committed))),
        (ev.counts.signups_excluded || ev.counts.interviews_excluded) ? h("p", { class: "tiny muted" }, ev.counts.signups_excluded + " signups and " + ev.counts.interviews_excluded + " conversations excluded (disclosed in the dossier).") : null),
      open && h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "6px" } }, "Send people to your page"),
        h("p", { class: "muted small" }, "Add ?s=name to the link to see which source works, e.g. ", h("code", {}, link + "?s=linkedin")),
        linkRow, s.protocol.traffic_plan ? h("p", { class: "small", style: { marginTop: "10px" } }, h("b", {}, "Your plan: "), s.protocol.traffic_plan) : null,
        channelTable && h("div", { style: { marginTop: "14px" } }, channelTable)),
      open && h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "6px" } }, "Log a conversation"),
        h("p", { class: "muted small" }, "Count Committed only when someone did something concrete: pre-ordered, agreed to a paid pilot, or booked a follow-up."),
        h("div", { class: "row3", style: { marginBottom: "12px" } }, outcome, who, notes), logBtn, h("div", { style: { marginTop: "14px" } }, signalsBox)),
      !open && h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "8px" } }, "Conversations"), signalsBox),
      h("div", { class: "sheet" }, h("div", { class: "spread", style: { marginBottom: "8px" } }, h("h3", {}, "Signups"), csvBtn), signupsBox),
      h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "6px" } }, "Share your evidence"),
        h("p", { class: "muted small" }, "A read-only page for mentors or investors: your locked rule, the counts, the verdict and any exclusions. It never shows emails."),
        dossier ? h("div", { class: "copy", style: { marginBottom: "10px" } }, h("input", { readOnly: true, value: dossier, "aria-label": "Dossier link" }),
          h("button", { class: "btn secondary", onclick: () => BZ.copy(dossier) }, "Copy"), h("a", { class: "btn secondary", href: dossier, target: "_blank", rel: "noopener" }, "Open")) : null,
        h("div", { class: "inline" }, dossierToggle, dossier ? rotate : null)),
      h("div", { class: "sheet" }, h("h3", { style: { marginBottom: "10px" } }, "Locked rule"),
        h("p", { class: "small", style: { margin: "0 0 6px" } }, h("b", {}, "Claim: "), s.protocol.claim),
        h("p", { class: "small", style: { margin: "0 0 6px" } }, h("b", {}, "Audience: "), s.protocol.audience),
        h("p", { class: "small", style: { margin: "0 0 6px" } }, h("b", {}, "Locked: "), BZ.date(s.locked_at), " (deadline ", BZ.day(s.protocol.deadline), ")"),
        h("div", { class: "hash" }, s.protocol_hash)),
      h("div", { class: "inline", style: { marginTop: "18px" } },
        open && concludeBtn, open && pauseBtn,
        h("button", { class: "btn danger", style: { marginLeft: "auto" }, onclick: () => BZ.confirm("Delete this test and all its data?", "The public page is removed and every signup, visit and note collected under it is permanently deleted.", "Delete everything",
          async () => { await BZ.api("/sprints/" + s.id, { method: "DELETE" }); ws.sprint = null; ws.view = "test"; await refresh(); }, true) }, "Delete test and data")));
  };
})();
