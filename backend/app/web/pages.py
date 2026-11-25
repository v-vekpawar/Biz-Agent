"""Server-rendered HTML: the public test page, the owner's preview, and the
shareable evidence dossier. Everything is self-contained (inline CSS/JS, system
fonts, no third-party requests) so visitors are never tracked by anyone else.

All dynamic text goes through html.escape; the inline script is nonce-protected
by the Content-Security-Policy set in app.main.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
from typing import Any

from ..services.stats import pct

e = html.escape

FONT = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif'

VERDICT_STYLE = {
    "go": ("Go", "#0F7B5F", "#E3F4EE"),
    "pivot": ("Pivot", "#9A5B00", "#FBF0DC"),
    "stop": ("Stop", "#B3261E", "#FBE6E4"),
    "keep_running": ("Still collecting data", "#3E4F6B", "#E8ECF3"),
    "inconclusive": ("Inconclusive", "#3E4F6B", "#E8ECF3"),
}


def fmt_dt(value: _dt.datetime | str | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        value = _dt.datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def fmt_date(value: str) -> str:
    return _dt.date.fromisoformat(value).strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# Threshold ruler (shared visual language with the app)
# ---------------------------------------------------------------------------

def ruler_svg(m: dict[str, Any], width: int = 640) -> str:
    """Horizontal ruler: stop zone | pivot zone | go zone, with the confidence
    interval and point estimate drawn on top."""
    f, s = m["failure_rate"], m["success_rate"]
    lo, hi, rate = m["lower"], m["upper"], m["rate"]
    top = max(s * 1.7, hi if m["trials"] else 0, 0.1)
    top = min(1.0, round(top + 0.04, 2))
    pad_l, pad_r = 8, 8
    span = width - pad_l - pad_r

    def x(v: float) -> float:
        return pad_l + (min(max(v, 0.0), top) / top) * span

    y0, h = 34, 22
    parts = [
        f'<svg viewBox="0 0 {width} 92" width="100%" role="img" aria-label="{e(m["label"])}: range {pct(lo)} to {pct(hi)} against floor {pct(f)} and target {pct(s)}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{x(0):.1f}" y="{y0}" width="{x(f) - x(0):.1f}" height="{h}" fill="#F4D7D4"/>',
        f'<rect x="{x(f):.1f}" y="{y0}" width="{x(s) - x(f):.1f}" height="{h}" fill="#F6E5C4"/>',
        f'<rect x="{x(s):.1f}" y="{y0}" width="{x(top) - x(s):.1f}" height="{h}" fill="#CDEBDF"/>',
        f'<line x1="{x(f):.1f}" y1="{y0 - 8}" x2="{x(f):.1f}" y2="{y0 + h + 8}" stroke="#7A3B36" stroke-width="1.5"/>',
        f'<line x1="{x(s):.1f}" y1="{y0 - 8}" x2="{x(s):.1f}" y2="{y0 + h + 8}" stroke="#0F5F49" stroke-width="1.5"/>',
        f'<text x="{x(f):.1f}" y="{y0 - 14}" font-size="12" text-anchor="middle" fill="#7A3B36">floor {pct(f)}</text>',
        f'<text x="{x(s):.1f}" y="{y0 - 14}" font-size="12" text-anchor="middle" fill="#0F5F49">target {pct(s)}</text>',
    ]
    if m["trials"] > 0:
        cy = y0 + h / 2
        parts += [
            f'<line x1="{x(lo):.1f}" y1="{cy}" x2="{x(hi):.1f}" y2="{cy}" stroke="#14202B" stroke-width="3"/>',
            f'<line x1="{x(lo):.1f}" y1="{cy - 7}" x2="{x(lo):.1f}" y2="{cy + 7}" stroke="#14202B" stroke-width="3"/>',
            f'<line x1="{x(hi):.1f}" y1="{cy - 7}" x2="{x(hi):.1f}" y2="{cy + 7}" stroke="#14202B" stroke-width="3"/>',
            f'<circle cx="{x(rate):.1f}" cy="{cy}" r="6" fill="#14202B" stroke="#fff" stroke-width="2"/>',
            f'<text x="{x(lo):.1f}" y="{y0 + h + 26}" font-size="12" text-anchor="middle" fill="#14202B">{pct(lo)}</text>',
            f'<text x="{x(hi):.1f}" y="{y0 + h + 26}" font-size="12" text-anchor="middle" fill="#14202B">{pct(hi)}</text>',
        ]
    else:
        parts.append(f'<text x="{width / 2}" y="{y0 + h / 2 + 4}" font-size="13" text-anchor="middle" fill="#5E6B78">no data yet</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public test page
# ---------------------------------------------------------------------------

_BASE_CSS = f"""
*{{box-sizing:border-box}}html{{-webkit-text-size-adjust:100%}}
:root{{
 --page-bg:#f2ede3;--page-card:#fbf8f1;--page-text:#211d1a;--page-muted:#71695f;
 --page-line:rgba(33,29,26,.15);--page-accent:#a9793a;--page-accent-ink:#fff;
 --page-banner:#211d1a;--page-soft:#eee2cf;--page-shadow:0 16px 42px rgba(33,29,26,.08)
}}
.theme-fresh_green{{--page-bg:#edf3eb;--page-card:#fbfdf8;--page-text:#1d2b23;--page-muted:#627064;--page-line:#d8e3d5;--page-accent:#477b55;--page-accent-ink:#fff;--page-banner:#203b2a;--page-soft:#e0ecdf}}
.theme-midnight_blue{{--page-bg:#edf1f7;--page-card:#fbfcff;--page-text:#18263b;--page-muted:#64738a;--page-line:#d8e0eb;--page-accent:#345b91;--page-accent-ink:#fff;--page-banner:#172b48;--page-soft:#e0e9f5}}
.theme-warm_citrus{{--page-bg:#fbf1df;--page-card:#fffaf0;--page-text:#342719;--page-muted:#806a4f;--page-line:#ead9b8;--page-accent:#bd762c;--page-accent-ink:#fff;--page-banner:#4b321d;--page-soft:#f5e4c4}}
.theme-violet_tech{{--page-bg:#f1eff8;--page-card:#fcfbff;--page-text:#28233d;--page-muted:#706a86;--page-line:#ded9ed;--page-accent:#7054a3;--page-accent-ink:#fff;--page-banner:#30234c;--page-soft:#e9e3f5}}
.theme-earth_clay{{--page-bg:#f3ece5;--page-card:#fffaf5;--page-text:#30231d;--page-muted:#78665b;--page-line:#e4d5c9;--page-accent:#a65d43;--page-accent-ink:#fff;--page-banner:#482c22;--page-soft:#efdfd4}}
.theme-rose_editorial{{--page-bg:#f6edf0;--page-card:#fffafd;--page-text:#34232b;--page-muted:#806b75;--page-line:#ead9e0;--page-accent:#a34e70;--page-accent-ink:#fff;--page-banner:#4a2938;--page-soft:#f1dfe7}}
.theme-paper_brass{{--page-bg:#f2ede3;--page-card:#fbf8f1;--page-text:#211d1a;--page-muted:#71695f;--page-line:rgba(33,29,26,.15);--page-accent:#a9793a;--page-accent-ink:#fff;--page-banner:#211d1a;--page-soft:#eee2cf}}
body{{margin:0;font-family:{FONT};color:var(--page-text);background:var(--page-bg);line-height:1.55}}
.wrap{{max-width:620px;margin:0 auto;padding:36px 20px 56px}}
.hero{{position:relative;overflow:hidden;background:var(--page-card);border:1px solid var(--page-line);border-radius:22px;padding:clamp(26px,5vw,44px);margin-bottom:20px;box-shadow:var(--page-shadow)}}
.hero:before{{content:"";position:absolute;width:340px;height:340px;border-radius:50%;left:-140px;bottom:-220px;background:var(--page-soft);opacity:.55}}
.hero:after{{content:"";position:absolute;width:220px;height:220px;border-radius:50%;right:-95px;top:-110px;background:var(--page-soft);opacity:.9}}
.hero-kicker{{position:relative;z-index:1;display:inline-block;font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase;color:var(--page-accent);margin:0 0 14px;padding:5px 10px;border:1px solid var(--page-soft);border-radius:99px;background:var(--page-card)}}
h1{{position:relative;z-index:1;font-size:clamp(28px,6vw,43px);line-height:1.08;margin:0 0 14px;letter-spacing:-.035em;max-width:15ch}}
.sub{{position:relative;z-index:1;font-size:18px;color:var(--page-muted);margin:0 0 4px;max-width:48ch}}
.style-editorial h1{{font-family:Georgia,serif;font-weight:600;letter-spacing:-.045em}}
.style-bold h1{{font-weight:850;letter-spacing:-.055em}}
.style-minimal .hero{{box-shadow:none;border-radius:12px}}
.style-playful .hero{{border-radius:30px 30px 12px 30px}}
ul.points{{list-style:none;padding:0;margin:0 0 22px;background:var(--page-card);border:1px solid var(--page-line);border-radius:16px;overflow:hidden;box-shadow:var(--page-shadow)}}
ul.points li{{display:flex;gap:12px;align-items:flex-start;padding:13px 18px;position:relative}}
ul.points li + li{{border-top:1px solid var(--page-soft)}}
ul.points li:before{{content:"";flex:none;width:16px;height:16px;margin-top:4px;border-radius:50%;background:var(--page-accent);opacity:.16}}
ul.points li:after{{content:"";position:absolute;left:21px;top:9px;width:8px;height:5px;border-left:2px solid var(--page-accent);border-bottom:2px solid var(--page-accent);transform:rotate(-45deg)}}
form{{background:var(--page-card);border:1px solid var(--page-line);border-radius:18px;padding:24px;box-shadow:var(--page-shadow)}}
.form-title{{font-size:16px;font-weight:750;margin:0 0 16px}}
label{{display:block;font-weight:650;font-size:14px;margin:0 0 6px}}
.qlabel{{font-weight:650;font-size:14px;margin:0 0 6px}}
input[type=email],input[type=text],textarea{{width:100%;font:inherit;padding:12px 13px;border:1px solid var(--page-line);border-radius:9px;background:var(--page-card);color:inherit}}
input:focus,textarea:focus,button:focus-visible,.choice:focus-within{{outline:3px solid var(--page-soft);outline-offset:2px}}
.field{{margin-bottom:16px}}
.field .optional{{font-weight:400;color:var(--page-muted)}}
.choices{{display:grid;gap:8px}}
.choice{{display:flex;gap:10px;align-items:center;font-size:15px;font-weight:500;padding:11px 13px;border:1px solid var(--page-line);border-radius:10px;cursor:pointer;background:var(--page-card)}}
.choice:hover{{border-color:var(--page-accent)}}
.choice input{{margin:0;width:17px;height:17px;flex:none;accent-color:var(--page-accent)}}
.consent{{display:flex;gap:10px;align-items:flex-start;font-size:14px;color:var(--page-muted);margin:4px 0 18px}}
.consent input{{margin-top:3px;width:18px;height:18px;flex:none;accent-color:var(--page-accent)}}
button{{font:inherit;font-weight:750;width:100%;padding:15px;border:0;border-radius:11px;background:var(--page-accent);color:var(--page-accent-ink);cursor:pointer;box-shadow:0 6px 18px -8px var(--page-accent)}}
.style-playful button{{border-radius:999px}}
button:hover{{filter:brightness(1.06)}}
button[disabled]{{opacity:.6;cursor:not-allowed;filter:none}}
.msg{{margin-top:14px;font-size:15px}}.err{{color:#a43d36}}.ok{{color:#286342;font-weight:650}}
.disclose{{margin-top:24px;font-size:13px;color:var(--page-muted)}}.disclose strong{{color:var(--page-text)}}
.disclose a{{color:var(--page-accent)}}
.hp{{position:absolute;left:-5000px;height:0;overflow:hidden}}
.banner{{background:var(--page-banner);color:#fff;font-size:13px;padding:8px 16px;text-align:center}}
@media(max-width:480px){{.wrap{{padding:20px 14px 36px}}.hero{{border-radius:16px;padding:24px 20px}}form{{padding:18px}}}}
"""


def _page_shell(title: str, body: str, *, nonce: str | None = None, script: str = "",
                banner: str = "", body_class: str = "") -> str:
    script_tag = f'<script nonce="{e(nonce)}">{script}</script>' if script and nonce else ""
    safe_class = " ".join(
        token for token in body_class.split()
        if token in {
            "theme-fresh_green", "theme-midnight_blue", "theme-warm_citrus",
            "theme-violet_tech", "theme-earth_clay", "theme-rose_editorial",
            "theme-paper_brass", "style-editorial", "style-bold", "style-minimal", "style-playful",
        }
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>{e(title)}</title><style>{_BASE_CSS}</style></head><body class=\"{e(safe_class)}\">{banner}{body}{script_tag}</body></html>"
    )


def _question_fields(questions: list[dict], disabled: str) -> str:
    """Render the page's questions: text inputs, textareas or radio pills."""
    blocks = []
    for question in questions:
        qid = question["id"]
        qtype = question.get("type") or "short_text"
        options = question.get("options") or []
        if qtype == "single_choice" and len(options) >= 2:
            radios = "".join(
                f'<label class="choice"><input type="radio" name="q_{e(qid)}" value="{e(option)}"{disabled}> {e(option)}</label>'
                for option in options
            )
            # A radio group has no single input to point a <label for> at, so
            # the group itself carries the question as its accessible name.
            blocks.append(
                f'<div class="field"><div class="qlabel">{e(question["label"])} <span class="optional">(optional)</span></div>'
                f'<div class="choices" role="radiogroup" aria-label="{e(question["label"])}">{radios}</div></div>'
            )
        elif qtype == "long_text":
            blocks.append(
                f'<div class="field"><label for="q_{e(qid)}">{e(question["label"])} <span class="optional">(optional)</span></label>'
                f'<textarea id="q_{e(qid)}" name="q_{e(qid)}" rows="3" maxlength="1000" '
                f'placeholder="Answer in your own words (optional)"{disabled}></textarea></div>'
            )
        else:
            blocks.append(
                f'<div class="field"><label for="q_{e(qid)}">{e(question["label"])} <span class="optional">(optional)</span></label>'
                f'<input type="text" id="q_{e(qid)}" name="q_{e(qid)}" maxlength="300" '
                f'placeholder="Type your answer (optional)"{disabled}></div>'
            )
    return "".join(blocks)


def render_public_page(sprint, content: dict[str, Any], *, nonce: str, mode: str = "live") -> str:
    """mode: live (collects data) | preview (owner draft, form disabled)."""
    bullets = "".join(f"<li><span>{e(b)}</span></li>" for b in content["bullets"])
    sub = f'<p class="sub">{e(content["subheadline"])}</p>' if content.get("subheadline") else ""
    # The page's questions: the structured list when present, else the legacy
    # single free-text question (old locked pages keep working unchanged).
    questions = [q for q in (content.get("questions") or [])
                 if isinstance(q, dict) and q.get("id") and q.get("label")]
    if not questions and content.get("extra_question"):
        questions = [{"id": "legacy", "label": content["extra_question"], "type": "long_text", "options": []}]
    question_html = _question_fields(questions, " disabled" if mode == "preview" else "")
    price = (f'<p class="sub" style="font-size:15px;margin:-10px 0 20px">Planned price: {e(content["price_hint"])}</p>'
             if content.get("price_hint") else "")
    disabled = " disabled" if mode == "preview" else ""
    theme = content.get("visual_theme", "paper_brass")
    if theme not in {"fresh_green", "midnight_blue", "warm_citrus", "violet_tech", "earth_clay", "rose_editorial", "paper_brass"}:
        theme = "paper_brass"
    style = content.get("visual_style", "editorial")
    if style not in {"editorial", "bold", "minimal", "playful"}:
        style = "editorial"
    kicker = f'<p class="hero-kicker">{e(content["hero_kicker"])}</p>' if content.get("hero_kicker") else ""
    body = f"""
<main class="wrap">
  <section class="hero">
    {kicker}
    <h1>{e(content["headline"])}</h1>
    {sub}
  </section>
  <ul class="points">{bullets}</ul>
  {price}
  <form id="f" novalidate>
    <p class="form-title">Join the waitlist</p>
    <div class="field"><label for="email">Your email</label>
      <input id="email" name="email" type="email" autocomplete="email" inputmode="email" required maxlength="254" placeholder="you@example.com"{disabled}></div>
    {question_html}
    <div class="hp" aria-hidden="true"><label>Leave this empty <input name="website" type="text" tabindex="-1" autocomplete="off"></label></div>
    <label class="consent"><input id="consent" type="checkbox"{disabled}><span>I agree to be contacted about this idea by email.</span></label>
    <button id="go" type="submit"{disabled}>{e(content["cta_label"])}</button>
    <div id="msg" class="msg" role="status" aria-live="polite"></div>
  </form>
  <p class="disclose"><strong>This is an early test.</strong> Nothing is for sale yet. Joining the list is not a purchase and commits you to nothing.
  We store only your email{' and your answers to the questions above' if questions else ''} to contact you about this idea. To have it deleted, email
  <a href="mailto:{e(content['contact_email'])}">{e(content['contact_email'])}</a>.
  A test by {e(content['creator_name'])}.</p>
</main>"""
    if mode == "preview":
        return _page_shell(content["headline"], body,
                           banner='<div class="banner">Preview. This is how visitors will see your page. The form is disabled.</div>',
                           body_class=f"theme-{theme} style-{style}")
    script = """
(function(){
  var slug=%s, api='/public/p/'+slug;
  var vid=null;
  try{vid=localStorage.getItem('bz_vid_'+slug);}catch(_){}
  if(!vid){vid=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():(Date.now().toString(36)+Math.random().toString(36).slice(2,12));
    try{localStorage.setItem('bz_vid_'+slug,vid);}catch(_){}}
  var q=new URLSearchParams(location.search), channel=q.get('s')||q.get('utm_source')||q.get('ref')||null;
  function post(path,body){return fetch(api+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  post('/visit',{vid:vid,channel:channel}).catch(function(){});
  var f=document.getElementById('f'),msg=document.getElementById('msg'),btn=document.getElementById('go');
  f.addEventListener('submit',function(ev){
    ev.preventDefault(); msg.className='msg'; msg.textContent='';
    var email=f.email.value.trim(), consent=document.getElementById('consent').checked;
    if(!email){msg.className='msg err';msg.textContent='Enter your email address.';return;}
    if(!consent){msg.className='msg err';msg.textContent='Please tick the box to agree to be contacted.';return;}
    btn.disabled=true;
    var answers={};
    f.querySelectorAll('[name^=q_]').forEach(function(el){
      if(el.type==='radio'){if(el.checked){answers[el.name.slice(2)]=el.value;}}
      else{var v=el.value.trim();if(v){answers[el.name.slice(2)]=v;}}
    });
    var hasQuestions=Object.keys(answers).length>0;
    post('/signup',{vid:vid,email:email,answer:hasQuestions?null:((f.querySelector('[name=answer]')||{}).value||null),
      answers:hasQuestions?answers:null,consent:consent,channel:channel,website:f.website.value})
      .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
      .then(function(r){
        if(r.ok){f.querySelectorAll('input,textarea').forEach(function(i){i.disabled=true;});btn.style.display='none';
          msg.className='msg ok';msg.textContent="You're on the list. Thank you.";}
        else{btn.disabled=false;msg.className='msg err';msg.textContent=(r.j&&r.j.detail&&typeof r.j.detail==='string')?r.j.detail:'Something went wrong. Please try again.';}
      }).catch(function(){btn.disabled=false;msg.className='msg err';msg.textContent='Network problem. Please try again.';});
  });
})();""" % json.dumps(sprint.slug)
    return _page_shell(content["headline"], body, nonce=nonce, script=script,
                       body_class=f"theme-{theme} style-{style}")


def render_message_page(title: str, message: str) -> str:
    body = f'<main class="wrap"><h1>{e(title)}</h1><p class="sub">{e(message)}</p></main>'
    return _page_shell(title, body)


# ---------------------------------------------------------------------------
# Dossier: a read-only evidence dashboard
# ---------------------------------------------------------------------------

_DOSSIER_CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;font-family:{FONT};color:#14202B;background:#EEF1F4;line-height:1.55}}
.page{{max-width:860px;margin:0 auto;padding:30px 20px 64px}}
.kicker{{font-size:13.5px;color:#5E6B78;margin:0 0 6px}}
h1{{font-size:clamp(26px,5vw,36px);line-height:1.15;margin:0 0 16px;letter-spacing:-.015em}}
h2{{font-size:15px;margin:30px 0 10px;text-transform:uppercase;letter-spacing:.07em;color:#5E6B78;font-weight:700}}
.card{{background:#fff;border:1px solid #D3DAE1;border-radius:14px;padding:18px 20px;margin:0 0 12px;box-shadow:0 10px 26px -18px rgba(20,32,43,.25)}}
.verdict{{border-radius:14px;padding:20px 22px;margin:0 0 14px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
.verdict b{{font-size:30px;display:block;line-height:1.1}}
.verdict .state{{font-size:14.5px}}
.verdict .next{{flex:1 1 300px;font-size:15px}}
.kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:0 0 14px}}
.kpi{{background:#fff;border:1px solid #D3DAE1;border-radius:12px;padding:14px 12px;text-align:center}}
.kpi b{{display:block;font-size:26px;line-height:1.1;margin-bottom:3px}}
.kpi span{{font-size:12px;color:#5E6B78}}
dl{{margin:0;display:grid;grid-template-columns:150px 1fr;gap:8px 16px;font-size:15px}}
dt{{color:#5E6B78}}dd{{margin:0;word-break:break-word}}
.hash{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;word-break:break-all}}
.nums{{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 4px;font-size:15px}}
.nums span b{{font-size:20px}}
.note{{font-size:14px;color:#3C4A57;margin:8px 0 0}}
.small{{font-size:13px;color:#5E6B78}}
.legend{{display:flex;gap:16px;font-size:13px;color:#5E6B78;margin:6px 0 0}}
.legend i{{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:7px 8px;border-bottom:1px solid #E2E7EC;text-align:left}}
th{{color:#5E6B78;font-weight:600}}
.trend{{display:block;margin-top:4px}}
@media(max-width:700px){{.kpis{{grid-template-columns:repeat(3,1fr)}}dl{{grid-template-columns:1fr}}.verdict{{flex-direction:column;align-items:flex-start;gap:8px}}}}
"""

_CHART_VISITOR = "#C9D6E4"
_CHART_SIGNUP = "#345B91"


def _kpi(value: str, label: str) -> str:
    return f'<div class="kpi"><b>{e(value)}</b><span>{e(label)}</span></div>'


def render_dossier(view: dict[str, Any], *, nonce: str | None = None) -> str:
    from ..reports.charts import trend_svg

    ev = view["evaluation"]
    label, fg, bg = VERDICT_STYLE[ev["verdict"]]
    final = view["final"]
    counts = view.get("counts") or ev.get("counts") or {}
    visitors, signups = counts.get("visitors", 0), counts.get("signups", 0)
    conversion = (signups / visitors) if visitors else None
    state_line = (
        f"Concluded {fmt_dt(view['concluded_at'])}" if final
        else ("Live reading. The test has not concluded." if not ev["finished"] else "The test window has closed; not yet concluded by its owner.")
    )

    kpis = "".join([
        _kpi(str(visitors), "Unique visitors"),
        _kpi(str(signups), "Signups"),
        _kpi(pct(conversion), "Conversion"),
        _kpi(str(counts.get("interviews", 0)), "Conversations"),
        _kpi(str(counts.get("committed", 0)), "Committed"),
        _kpi(str(view.get("days_live") or 1), "Days live"),
    ])

    metric_blocks = []
    for m in ev["metrics"]:
        mlabel, mfg, mbg = VERDICT_STYLE[m["verdict"]]
        metric_blocks.append(f"""
<section class="card">
  <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap">
    <strong>{e(m['label'])}{' (decides the verdict)' if m['role'] == 'primary' else ' (supporting)'}</strong>
    <span style="color:{mfg};background:{mbg};padding:2px 10px;border-radius:99px;font-size:13px;font-weight:600">{e(mlabel)}</span>
  </div>
  <div class="nums"><span><b>{m['successes']}</b> of <b>{m['trials']}</b> {e(m['trial_unit'])}</span><span><b>{pct(m['rate'])}</b> observed</span></div>
  {ruler_svg(m)}
  <p class="note">{e(m['reason'])}</p>
  <p class="small">Range is a {int(m['confidence'] * 100)}% Wilson score interval. Minimum sample before any call: {m['min_sample']}.</p>
</section>""")

    notes = "".join(f'<p class="note">{e(n)}</p>' for n in ev["notes"])
    exclusions = ""
    if view["exclusions"]:
        rows = "".join(f"<tr><td>{e(x['kind'])}</td><td>{e(x['reason'] or '')}</td></tr>" for x in view["exclusions"])
        exclusions = (f'<h2>Entries the owner excluded</h2><div class="card"><p class="small" style="margin-top:0">'
                      f"Excluded entries are removed from the counts above, never deleted, and always disclosed here.</p>"
                      f"<table><tr><th>Entry</th><th>Reason given</th></tr>{rows}</table></div>")

    series = view.get("series") or []
    trend = trend_svg(series)
    trend_section = f"""
<h2>Where the numbers came from</h2>
<div class="card">
  {trend}
  <p class="legend"><span><i style="background:{_CHART_VISITOR}"></i>Unique visitors per day</span>
  <span><i style="background:{_CHART_SIGNUP}"></i>Waitlist signups per day</span></p>
  <p class="small">Visitors are counted once per browser; signups once per email. Long tests are grouped per week.</p>
</div>"""

    channels = view.get("channels") or []
    channels_section = ""
    if channels:
        rows = "".join(
            f"<tr><td>{e(c['channel'])}</td><td>{c['visitors']}</td><td>{c['signups']}</td>"
            f"<td>{pct(c['signups'] / c['visitors']) if c['visitors'] else 'n/a'}</td></tr>"
            for c in channels
        )
        channels_section = f"""
<h2>Which sources worked</h2>
<div class="card"><table><tr><th>Source</th><th>Visitors</th><th>Signups</th><th>Conversion</th></tr>{rows}</table></div>"""

    body = f"""
<main class="page">
  <p class="kicker">Validation dossier by {e(view['owner_name'])}</p>
  <h1>{e(view['headline'])}</h1>

  <div class="verdict" style="background:{bg};color:{fg}">
    <div><b>{e(label)}</b><span class="state">{e(state_line)}</span></div>
    <div class="next">{e(ev['next_step'])}</div>
  </div>

  <div class="kpis">{kpis}</div>
  {notes}

  <h2>What was tested</h2>
  <div class="card"><dl>
    <dt>Claim</dt><dd>{e(view['claim'])}</dd>
    <dt>Audience</dt><dd>{e(view['audience'])}</dd>
    {f"<dt>Traffic plan</dt><dd>{e(view['traffic_plan'])}</dd>" if view.get('traffic_plan') else ''}
    <dt>Deadline</dt><dd>{fmt_date(view['deadline'])} (end of day, UTC)</dd>
    <dt>Locked</dt><dd>{fmt_dt(view['locked_at'])}, before any data was collected</dd>
  </dl></div>

  {trend_section}
  {channels_section}

  <h2>Results against the locked rule</h2>
  {''.join(metric_blocks)}
  {exclusions}

  <h2>Pre-registration</h2>
  <div class="card">
    <p style="margin:0 0 10px">The page copy, the claim and the decision rule were locked <b>{fmt_dt(view['locked_at'])}</b>, before any data was collected, and cannot be edited afterwards. This fingerprint covers all of it:</p>
    <p class="hash" style="margin:0">{e(view['protocol_hash'] or '')}</p>
  </div>

  <h2>How to read this</h2>
  <div class="card small" style="color:#3C4A57">
    The verdict is computed by a fixed rule from the counts, not written by an AI. <b>Go</b>: the cautious end of the range clears the target.
    <b>Stop</b>: the optimistic end is below the floor. <b>Pivot</b>: the whole range sits between floor and target.
    Anything else keeps running until the minimum sample is reached or the deadline passes. Visitors are counted once per browser; signups once per email.
    A waitlist signup is evidence of interest, not of willingness to pay.
  </div>
  <p class="small" style="margin-top:20px">Generated by Biz-Agent. No emails or personal answers appear in this dossier.</p>
</main>"""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>Validation dossier: {e(view['headline'])}</title><style>{_DOSSIER_CSS}</style></head><body>{body}</body></html>"
    )
