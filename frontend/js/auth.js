(function () {
  const { h } = BZ;

  BZ.authView = (mode) => (app) => {
    const registering = mode === "register";
    const err = h("div", { class: "err", role: "alert" });
    const email = h("input", { id: "email", type: "email", autocomplete: "email", required: true, maxLength: 254 });
    const pass = h("input", { id: "pw", type: "password", autocomplete: registering ? "new-password" : "current-password", required: true, maxLength: 200 });
    const name = h("input", { id: "nm", type: "text", autocomplete: "name", maxLength: 100 });
    const submit = h("button", { class: "btn", type: "submit" }, registering ? "Create account" : "Sign in");

    const form = h("form", { novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault(); err.textContent = ""; submit.disabled = true;
        try {
          const out = await BZ.api(registering ? "/auth/register" : "/auth/login", { method: "POST", noAuthRedirect: true,
            body: registering ? { email: email.value, password: pass.value, display_name: name.value } : { email: email.value, password: pass.value } });
          BZ.setSession(out.access_token, out.user);
          location.hash = "#/";
        } catch (ex) { err.textContent = ex.message; } finally { submit.disabled = false; }
      } },
      h("h2", {}, registering ? "Create your account" : "Sign in"),
      registering && h("div", { class: "field" }, h("label", { for: "nm" }, "Your name"), name,
        h("div", { class: "hint" }, "Shown on your public test pages.")),
      h("div", { class: "field" }, h("label", { for: "email" }, "Email"), email),
      h("div", { class: "field" }, h("label", { for: "pw" }, "Password"), pass,
        registering && h("div", { class: "hint" }, "At least 8 characters.")),
      err, submit,
      h("p", { class: "swap muted" }, registering ? "Already have an account? " : "New here? ",
        h("a", { href: registering ? "#/login" : "#/register" }, registering ? "Sign in" : "Create an account")));

    app.append(h("div", { class: "wrap" }, h("div", { class: "auth" },
      h("div", {},
        h("h1", {}, "Find out if people want it before you build it."),
        h("p", { class: "lead" }, "Biz-Agent finds what is most likely to sink your idea, then helps you test it with real people against a bar you set in advance."),
        h("ol", {},
          h("li", {}, "A risk scan ranks your riskiest assumptions, with sources."),
          h("li", {}, "You lock a customer test: a public page and a pass/fail rule."),
          h("li", {}, "Real signups decide the verdict. Not an AI's opinion, and not wishful thinking."))),
      form)));
    (registering ? name : email).focus();
  };
})();
