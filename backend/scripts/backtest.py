"""Backtest the risk scan against startups whose failure reasons are publicly documented.

    python scripts/backtest.py evaluation/cases.json --base http://localhost:8000 \
        --email you@example.com --password '...'

Each case lists the idea as it looked at launch and the categories of the documented
failure causes. A case is a HIT when at least one of the scan's top-3 ranked risks falls in
one of those categories. The script prints a table, the hit rate, and writes results.json.

This measures one narrow thing (does desk research point at the thing that actually
killed it?). It does not measure whether the verdict engine is right; that is statistics,
covered by the unit tests, and the live case study.
"""
import argparse
import json
import sys
import time

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait per scan")
    args = ap.parse_args()

    cases = json.load(open(args.cases, encoding="utf-8"))
    c = httpx.Client(base_url=args.base + "/api/v1", timeout=120)
    r = c.post("/auth/login", json={"email": args.email, "password": args.password})
    if r.status_code != 200:
        r = c.post("/auth/register", json={"email": args.email, "password": args.password, "display_name": "Backtest"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    results = []
    for case in cases:
        if case.get("_placeholder"):
            print(f"skip placeholder: {case['title']}")
            continue
        body = {k: case[k] for k in ("title", "idea_description", "target_customer", "customer_problem",
                                     "pricing_model", "geography", "known_competitors") if case.get(k)}
        cid = c.post("/business-cases", headers=h, json=body).json()["id"]
        c.post(f"/business-cases/{cid}/scan", headers=h)
        deadline = time.time() + args.timeout
        job = None
        while time.time() < deadline:
            job = c.get(f"/business-cases/{cid}/scan", headers=h).json()["job"]
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(5)
        if not job or job["status"] != "completed":
            results.append({"title": case["title"], "status": "scan_failed", "error": (job or {}).get("error")})
            continue
        risks = c.get(f"/business-cases/{cid}/risks", headers=h).json()["risks"][:3]
        got = [r["category"] for r in risks]
        expected = set(case["known_failure_categories"])
        results.append({"title": case["title"], "status": "ok", "top3_categories": got,
                        "expected": sorted(expected), "hit": bool(expected & set(got)),
                        "source_note": case.get("source_note")})

    ok = [r for r in results if r["status"] == "ok"]
    print(f"\n{'case':42} {'hit':5} top-3 categories")
    for r in results:
        print(f"{r['title'][:40]:42} {str(r.get('hit', '-')):5} {r.get('top3_categories', r.get('error'))}")
    if ok:
        hits = sum(r["hit"] for r in ok)
        print(f"\nHit rate: {hits}/{len(ok)} = {hits / len(ok):.0%}")
    json.dump(results, open("results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
