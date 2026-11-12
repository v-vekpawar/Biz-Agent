"""Browser end-to-end smoke test (Playwright + Chromium).

Drives the real app through: register, add idea, write a manual test, preview,
lock, collect real signups from separate browser contexts, log conversations,
open the dossier, download the PDF brief, and conclude.

    pip install playwright && playwright install chromium
    # start the server with a throwaway database:
    DATABASE_URL=sqlite:////tmp/e2e.db BIZAGENT_SECRET_KEY=x BIZAGENT_RATE_LIMIT=off \
        uvicorn app.main:app --port 8000
    python scripts/e2e_smoke.py [http://localhost:8000]
"""
import sys
import time

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
UID = str(int(time.time()))
js_errors: list = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1180, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: js_errors.append(str(e)))

    page.goto(BASE + "/app/")
    page.get_by_role("link", name="Create an account").click()
    page.fill("#nm", "Asha"); page.fill("#email", f"asha{UID}@example.com"); page.fill("#pw", "correct-horse-1")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Your ideas")).to_be_visible()

    page.get_by_role("link", name="Add your first idea").click()
    page.fill("#title", "Small-batch chai subscription")
    page.fill("#idea_description", "A monthly box of single-estate chai blends delivered to office desks in Pune.")
    page.fill("#target_customer", "Office workers in Pune"); page.fill("#pricing_model", "INR 499 per month")
    page.get_by_role("button", name="Save and continue").click()
    expect(page.get_by_role("heading", name="Small-batch chai subscription")).to_be_visible()

    page.locator(".rail button", has_text="Customer test").click()
    page.get_by_role("button", name="Write it myself").click()
    page.fill("#bullets", "Six single-estate blends\nCancel any time")
    page.fill("#n1", "30")
    page.get_by_role("tab", name="Preview page").click()
    expect(page.frame_locator("iframe.preview").get_by_role("heading", name="Small-batch chai subscription")).to_be_visible(timeout=10000)
    page.get_by_role("tab", name="Setup").click()
    page.get_by_role("button", name="Review and lock").click()
    page.get_by_role("button", name="Lock and go live").click()
    expect(page.locator(".modal .err")).to_contain_text("Confirm both statements")
    page.check("#ack1"); page.check("#ack2")
    page.get_by_role("button", name="Lock and go live").click()
    expect(page.locator(".verdict .word")).to_have_text("Still collecting data", timeout=10000)
    link = page.locator('input[aria-label="Public page link"]').input_value()

    for i in range(34):  # each visitor is a separate browser context (separate localStorage)
        v_ctx = browser.new_context(viewport={"width": 390, "height": 800})
        v = v_ctx.new_page()
        v.goto(link + ("?s=linkedin" if i % 2 else ""))
        v.wait_for_load_state("networkidle")
        if i < 12:
            v.fill("#email", f"person{i}@example.com"); v.check("#consent")
            v.get_by_role("button", name="Join the waitlist").click()
            expect(v.locator("#msg")).to_contain_text("You're on the list", timeout=8000)
        v_ctx.close()

    page.reload()
    page.locator(".rail button", has_text="Customer test").click()
    expect(page.locator(".verdict .word")).to_have_text("Go", timeout=10000)

    page.get_by_role("button", name="Create a shareable dossier").click()
    dossier = page.locator('input[aria-label="Dossier link"]').input_value()
    d_ctx = browser.new_context(); d = d_ctx.new_page(); d.goto(dossier)
    expect(d.get_by_role("heading", name="Small-batch chai subscription")).to_be_visible()
    assert "person0@example.com" not in d.content(), "dossier must never show emails"

    with page.expect_download() as dl:
        page.get_by_role("button", name="Download decision brief").click()
    assert dl.value.suggested_filename.endswith("decision-brief.pdf")

    page.get_by_role("button", name="Conclude the test").click()
    page.get_by_role("button", name="Record result").click()
    page.locator(".rail button", has_text="Decision").click()
    expect(page.locator(".verdict .word")).to_have_text("Go")
    browser.close()

assert not js_errors, js_errors
print("E2E OK")
