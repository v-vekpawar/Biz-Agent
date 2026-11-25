"""The dashboard visuals: dossier KPIs/trend/channels and the PDF stat band + actions."""

from __future__ import annotations

from conftest import LOCK, sprint_payload

API = "/api/v1"


def _drive_traffic(client, slug, *, visitors=40, signups=12, channels=("linkedin", "direct")):
    for i in range(visitors):
        channel = channels[i % len(channels)]
        vid = f"visitor-{i:04d}-abcdef"
        client.post(f"/public/p/{slug}/visit", json={"vid": vid, "channel": channel})
        if i < signups:
            client.post(f"/public/p/{slug}/signup", json={
                "vid": vid, "email": f"person{i}@example.com", "consent": True, "channel": channel})
    client.post(f"/api/v1/sprints/0/signals", json={"outcome": "committed"}) if False else None


def _live_sprint_with_dossier(client, auth, case_id):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    locked = client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK).json()
    _drive_traffic(client, draft["slug"], visitors=40, signups=12)
    client.post(f"/api/v1/sprints/{draft['id']}/signals", headers=auth, json={"outcome": "committed", "who": "Ravi"})
    client.post(f"/api/v1/sprints/{draft['id']}/signals", headers=auth, json={"outcome": "interested", "who": "Meera"})
    on = client.post(f"{API}/sprints/{draft['id']}/dossier", headers=auth, json={"enabled": True}).json()
    return draft, locked, on


def test_dossier_renders_the_dashboard(client, auth, case_id):
    _draft, _locked, live = _live_sprint_with_dossier(client, auth, case_id)
    r = client.get(live["links"]["dossier"])
    assert r.status_code == 200
    html = r.text
    # KPI cards carry the real counts
    assert "Unique visitors" in html and "Signups" in html and "Conversion" in html
    assert "<b>40</b>" in html and "<b>12</b>" in html
    assert "Conversations" in html and "Committed" in html and "Days live" in html
    # the daily traffic chart is server-rendered SVG with a legend
    assert 'aria-label="Daily visitors and signups' in html and "<svg" in html
    assert "Unique visitors per day" in html and "Waitlist signups per day" in html
    # channel breakdown with conversion
    assert "Which sources worked" in html and "linkedin" in html
    # pre-registration + honesty blocks stay
    assert "Pre-registration" in html and "How to read this" in html
    # self-contained, CSP-safe: no scripts, no external requests
    assert "<script" not in html and "http://" not in html.replace("http://www.w3.org", "")


def test_dossier_without_traffic_shows_an_honest_empty_chart(client, auth, case_id):
    draft = client.post(f"{API}/business-cases/{case_id}/sprints", headers=auth, json=sprint_payload()).json()
    client.post(f"{API}/sprints/{draft['id']}/lock", headers=auth, json=LOCK)
    on = client.post(f"{API}/sprints/{draft['id']}/dossier", headers=auth, json={"enabled": True}).json()
    html = client.get(on["links"]["dossier"]).text
    assert "No traffic yet" in html
    assert "Which sources worked" not in html  # no channel table without data


def test_trend_geometry_buckets_long_tests_per_week():
    import datetime as dt

    from app.reports.charts import trend_geometry

    start = dt.date(2026, 1, 1)
    series = [{"date": (start + dt.timedelta(days=i)).isoformat(), "visitors": 5, "signups": 1}
              for i in range(45)]
    g = trend_geometry(series, width=680, height=150)
    assert 5 <= len(g["rows"]) <= 8  # 45 days collapse into ~7 weekly buckets
    assert g["peak"] == 35  # a full 7-day bucket of 5 visitors/day
    assert g["bars"] and g["bars"][0]["vh"] > g["bars"][0]["sh"]  # visitors tower over signups


def test_trend_svg_never_renders_unsafe_text():
    from app.reports.charts import trend_svg

    series = [{"date": "2026-01-0<script>", "visitors": 3, "signups": 1}]
    svg = trend_svg(series)
    assert "<script" not in svg


def test_brief_pdf_carries_decisions_and_stat_band(client, auth, case_id):
    import io

    from pypdf import PdfReader

    _draft, _locked, _live = _live_sprint_with_dossier(client, auth, case_id)
    r = client.get(f"{API}/business-cases/{case_id}/brief.pdf", headers=auth)
    assert r.status_code == 200
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    # the action list from the decision tab now leads the PDF too
    assert "What you should do next" in text and "NOW" in text
    # the stat band shows the same counts as the dossier
    assert "Visitors" in text and "Conversion" in text
    assert "Conversations" in text and "Committed" in text
    # the daily trend chart renders with its caption
    assert "per day since the test was locked" in text
