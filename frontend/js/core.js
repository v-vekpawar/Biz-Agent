/* Biz-Agent core: DOM builder, API client, session, router, small UI helpers.
   Every piece of dynamic text goes through h() (textContent), never innerHTML. */
(function () {
  const BZ = (window.BZ = {});
  const TOKEN_KEY = "bz_token", USER_KEY = "bz_user";

  // ---- session -----------------------------------------------------------
  BZ.token = () => { try { return localStorage.getItem(TOKEN_KEY); } catch (_) { return null; } };
  BZ.user = () => { try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch (_) { return null; } };
  BZ.setSession = (token, user) => { try { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)); } catch (_) {} };
  BZ.clearSession = () => { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch (_) {} };

  // Element.append() turns null/false into the text "null"/"false" and arrays into
  // "[object ...]". Make it behave like the builder below: skip empties, flatten arrays.
  const nativeAppend = Element.prototype.append;
  Element.prototype.append = function (...kids) {
    const flat = [];
    const walk = (k) => { if (k === null || k === undefined || k === false) return; if (Array.isArray(k)) return k.forEach(walk); flat.push(k); };
    kids.forEach(walk);
    return nativeAppend.apply(this, flat);
  };

  // ---- DOM builder ---------------------------------------------------------
  BZ.h = function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k.startsWith("aria-") && typeof v === "boolean") { el.setAttribute(k, String(v)); continue; }  // aria-selected="false" must stay explicit
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k in el && k !== "list" && k !== "type" && k !== "form") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    const add = (kid) => {
      if (kid === null || kid === undefined || kid === false) return;
      if (Array.isArray(kid)) return kid.forEach(add);
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    };
    kids.forEach(add);
    return el;
  };
  const h = BZ.h;
  BZ.clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

  // ---- API ---------------------------------------------------------------------
  function detailMessage(data, status) {
    const d = data && data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => {
        const field = (e.loc || []).filter((p) => p !== "body").slice(-1)[0];
        return (field ? String(field).replace(/_/g, " ") + ": " : "") + (e.msg || "invalid").replace(/^Value error, /, "");
      }).join("; ");
    }
    if (status === 429) return "Too many attempts. Wait a moment and try again.";
    if (status >= 500) return "Something went wrong on the server. Try again.";
    return "Request failed (" + status + ").";
  }

  BZ.api = async function api(path, opts = {}) {
    const headers = {};
    const token = BZ.token();
    if (token) headers.Authorization = "Bearer " + token;
    let body;
    if (opts.body instanceof FormData) body = opts.body;
    else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
    let res;
    try {
      res = await fetch((window.BZ_API_BASE || "") + "/api/v1" + path, { method: opts.method || "GET", headers, body });
    } catch (_) {
      throw new Error("Can't reach the server. Check your connection.");
    }
    if (res.status === 401 && !opts.noAuthRedirect) {
      BZ.clearSession(); BZ.topbar(); location.hash = "#/login";
      throw new Error("Please sign in again.");
    }
    if (opts.blob) {
      if (!res.ok) throw new Error(detailMessage(await res.json().catch(() => null), res.status));
      return { blob: await res.blob(), filename: (/filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "") || [])[1] };
    }
    if (opts.text) {
      const text = await res.text();
      if (!res.ok) throw new Error(detailMessage(null, res.status));
      return text;
    }
    const data = res.status === 204 ? null : await res.json().catch(() => null);
    if (!res.ok) throw new Error(detailMessage(data, res.status));
    return data;
  };

  // ---- helpers ---------------------------------------------------------------------
  BZ.pct = (v) => (v === null || v === undefined ? "n/a" : (v * 100).toFixed(1).replace(/\.0$/, "") + "%");
  BZ.date = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "");
  BZ.day = (iso) => (iso ? new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");
  BZ.pluralize = (n, word) => n + " " + word + (n === 1 ? "" : "s");

  BZ.toast = (msg, bad) => {
    const t = h("div", { class: "toast" + (bad ? " bad" : ""), role: bad ? "alert" : "status" }, msg);
    document.getElementById("toasts").append(t);
    setTimeout(() => t.remove(), bad ? 7000 : 3500);
  };
  BZ.copy = async (text) => {
    try { await navigator.clipboard.writeText(text); BZ.toast("Copied"); }
    catch (_) { BZ.toast("Copy failed. Select the text and copy it manually.", true); }
  };
  BZ.save = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: filename });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  };

  /** Button wrapper: disables while the async action runs; surfaces errors as toasts. */
  BZ.action = (btn, fn) => async (ev) => {
    ev && ev.preventDefault && ev.preventDefault();
    if (btn.disabled) return;
    const label = btn.textContent; btn.disabled = true;
    try { await fn(); } catch (e) { BZ.toast(e.message, true); } finally { btn.disabled = false; btn.textContent = label; }
  };

  BZ.modal = ({ title, body, actions }) => {
    const prev = document.activeElement;
    const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); prev && prev.focus && prev.focus(); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    const scrim = h("div", { class: "scrim", onclick: (e) => e.target === scrim && close() },
      h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
        h("h2", {}, title), body, h("div", { class: "actions" }, actions(close))));
    document.addEventListener("keydown", onKey);
    document.body.append(scrim);
    const first = scrim.querySelector("input,button,textarea,select"); first && first.focus();
    return close;
  };
  BZ.confirm = (title, message, confirmLabel, onConfirm, danger) => BZ.modal({
    title, body: h("p", {}, message),
    actions: (close) => [
      h("button", { class: "btn secondary", onclick: close }, "Cancel"),
      h("button", { class: "btn" + (danger ? " danger" : ""), onclick: async (e) => {
        const b = e.currentTarget; b.disabled = true;
        try { await onConfirm(); close(); } catch (err) { b.disabled = false; BZ.toast(err.message, true); }
      } }, confirmLabel),
    ],
  });

  // ---- threshold ruler (same visual language as the public dossier) ----------------------
  BZ.ruler = function ruler(m) {
    const NS = "http://www.w3.org/2000/svg", W = 640;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " 92"); svg.setAttribute("class", "ruler"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", m.label + ": range " + BZ.pct(m.lower) + " to " + BZ.pct(m.upper) + " against floor " + BZ.pct(m.failure_rate) + " and target " + BZ.pct(m.success_rate));
    const f = m.failure_rate, s = m.success_rate;
    const top = Math.min(1, Math.round((Math.max(s * 1.7, m.trials ? m.upper : 0, 0.1) + 0.04) * 100) / 100);
    const x = (v) => 8 + (Math.min(Math.max(v, 0), top) / top) * (W - 16);
    const el = (name, attrs, text) => { const n = document.createElementNS(NS, name); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text) n.textContent = text; svg.append(n); return n; };
    const y0 = 34, hh = 22, cy = y0 + hh / 2;
    el("rect", { x: x(0), y: y0, width: x(f) - x(0), height: hh, fill: "#f1dfda" });
    el("rect", { x: x(f), y: y0, width: x(s) - x(f), height: hh, fill: "#f3e7d4" });
    el("rect", { x: x(s), y: y0, width: x(top) - x(s), height: hh, fill: "#e1e9e1" });
    el("line", { x1: x(f), y1: y0 - 8, x2: x(f), y2: y0 + hh + 8, stroke: "#9b3f35", "stroke-width": 1.5 });
    el("line", { x1: x(s), y1: y0 - 8, x2: x(s), y2: y0 + hh + 8, stroke: "#1c2a24", "stroke-width": 1.5 });
    el("text", { x: x(f), y: y0 - 14, "font-size": 12, "text-anchor": "middle", fill: "#9b3f35" }, "floor " + BZ.pct(f));
    el("text", { x: x(s), y: y0 - 14, "font-size": 12, "text-anchor": "middle", fill: "#1c2a24" }, "target " + BZ.pct(s));
    if (m.trials > 0) {
      el("line", { x1: x(m.lower), y1: cy, x2: x(m.upper), y2: cy, stroke: "#211d1a", "stroke-width": 3 });
      el("line", { x1: x(m.lower), y1: cy - 7, x2: x(m.lower), y2: cy + 7, stroke: "#211d1a", "stroke-width": 3 });
      el("line", { x1: x(m.upper), y1: cy - 7, x2: x(m.upper), y2: cy + 7, stroke: "#211d1a", "stroke-width": 3 });
      el("circle", { cx: x(m.rate), cy, r: 6, fill: "#211d1a", stroke: "#fff", "stroke-width": 2 });
      el("text", { x: x(m.lower), y: y0 + hh + 26, "font-size": 12, "text-anchor": "middle", fill: "#211d1a" }, BZ.pct(m.lower));
      el("text", { x: x(m.upper), y: y0 + hh + 26, "font-size": 12, "text-anchor": "middle", fill: "#211d1a" }, BZ.pct(m.upper));
    } else {
      el("text", { x: W / 2, y: cy + 4, "font-size": 13, "text-anchor": "middle", fill: "#71695f" }, "no data yet");
    }
    return svg;
  };

  BZ.VERDICT = {
    go: "Go", pivot: "Pivot", stop: "Stop", keep_running: "Still collecting data", inconclusive: "Inconclusive",
  };

  // ---- topbar + router -----------------------------------------------------------------------
  BZ.topbar = () => {
    const bar = BZ.clear(document.getElementById("topbar"));
    const user = BZ.user();
    bar.append(h("a", { class: "brand", href: BZ.token() ? "#/" : "#/login" }, "Biz-Agent"));
    if (BZ.token() && user) {
      bar.append(h("div", { class: "who" }, h("span", {}, user.display_name),
        h("button", { class: "btn quiet small", onclick: async () => {
          try {
            const status = await BZ.api("/ai/providers");
            const rows = (status.providers || []).map((p) => h("div", { class: "spread", style: { padding: "7px 0", borderBottom: "1px solid var(--line-soft)" } },
              h("span", {}, h("b", {}, p.provider), h("small", { class: "muted", style: { display: "block" } }, p.model)),
              h("span", { class: p.configured ? "status-good" : "muted" }, p.configured ? "Configured" : "Not configured")));
            BZ.modal({ title: "AI provider fallback", body: h("div", {},
              h("p", { class: "muted small" }, "Free-only routing. Biz-Agent never automatically switches to a paid model."),
              h("p", {}, "Fallback order: ", h("b", {}, (status.fallback_order || []).join(" → ") || "No providers configured")),
              ...rows,
              h("p", { class: "hint", style: { marginTop: "12px" } }, status.note || "")),
              actions: (close) => [h("button", { class: "btn", onclick: close }, "Close")] });
          } catch (e) { BZ.toast(e.message, true); }
        } }, "AI providers"),
        h("button", { class: "btn quiet small", onclick: () => { BZ.clearSession(); BZ.topbar(); location.hash = "#/login"; } }, "Sign out")));
    }
  };

  const routes = [];
  let cleanup = null;
  BZ.route = (pattern, handler, opts = {}) => routes.push({ re: new RegExp("^" + pattern.replace(/:(\w+)/g, "(?<$1>[^/]+)") + "$"), handler, public: !!opts.public });
  BZ.go = (hash) => { if (location.hash === hash) BZ.render(); else location.hash = hash; };
  BZ.render = async function render() {
    if (cleanup) { try { cleanup(); } catch (_) {} cleanup = null; }
    const path = (location.hash.replace(/^#/, "") || "/").split("?")[0];
    const app = document.getElementById("app");
    BZ.topbar();
    for (const r of routes) {
      const m = r.re.exec(path);
      if (!m) continue;
      if (!r.public && !BZ.token()) { location.hash = "#/login"; return; }
      if (r.public && BZ.token() && (path === "/login" || path === "/register")) { location.hash = "#/"; return; }
      BZ.clear(app);
      try { const out = await r.handler(app, m.groups || {}); if (typeof out === "function") cleanup = out; }
      catch (e) { BZ.clear(app).append(h("div", { class: "wrap narrow" }, h("h2", {}, "Something went wrong"), h("p", { class: "err" }, e.message), h("a", { class: "btn secondary", href: "#/" }, "Back to your ideas"))); }
      window.scrollTo(0, 0);
      return;
    }
    BZ.clear(app).append(h("div", { class: "wrap narrow" }, h("h2", {}, "Page not found"), h("a", { href: "#/" }, "Back to your ideas")));
  };
  window.addEventListener("hashchange", () => BZ.render());
})();
