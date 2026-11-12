"""Send SIMULATED visitors and signups to a test page, to exercise the verdict engine.

    python scripts/simulate_traffic.py http://localhost:8000/p/abc123 --visitors 60 --signups 12

FOR TESTING ONLY. These are fake people: never use this on a test whose result you intend to
report as evidence. Start the server with BIZAGENT_RATE_LIMIT=off for large runs.
"""
import argparse
import sys
import uuid
from urllib.parse import urlparse

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page_url", help="the public test page link, e.g. http://localhost:8000/p/abc123")
    ap.add_argument("--visitors", type=int, required=True)
    ap.add_argument("--signups", type=int, required=True, help="how many of the visitors sign up")
    ap.add_argument("--channel", default="simulated")
    args = ap.parse_args()
    if args.signups > args.visitors:
        print("signups cannot exceed visitors"); return 2
    u = urlparse(args.page_url)
    slug = u.path.rstrip("/").split("/")[-1]
    base = f"{u.scheme}://{u.netloc}/public/p/{slug}"
    run = uuid.uuid4().hex[:6]
    ok_v = ok_s = 0
    with httpx.Client(timeout=15) as c:
        for i in range(args.visitors):
            vid = f"sim-{run}-{i:05d}"
            r = c.post(base + "/visit", json={"vid": vid, "channel": args.channel})
            if r.status_code == 429:
                print("Rate limited. Restart the server with BIZAGENT_RATE_LIMIT=off for simulations."); return 1
            if r.status_code != 200:
                print(f"visit failed: {r.status_code} {r.text}"); return 1
            ok_v += 1
            if i < args.signups:
                r = c.post(base + "/signup", json={"vid": vid, "email": f"sim-{run}-{i}@example.test", "consent": True,
                                                   "channel": args.channel, "answer": "simulated"})
                if r.status_code != 200:
                    print(f"signup failed: {r.status_code} {r.text}"); return 1
                ok_s += 1
    print(f"sent {ok_v} visitors, {ok_s} signups to {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
