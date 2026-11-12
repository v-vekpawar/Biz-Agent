# Test the whole workflow, step by step

Sample idea: a hostel-night snack box. About 45 minutes the first time (the scan takes 1 to 3 minutes of that).

## 0. Setup (5 min)

1. `cp .env.example .env` and set: `BIZAGENT_SECRET_KEY` (any long random string), `GOOGLE_API_KEY` and/or `GROQ_API_KEY`, `TAVILY_API_KEY`.
2. `cd backend && uvicorn app.main:app --reload --port 8000`
3. Open <http://localhost:8000>. You should see the sign-in page.
4. For the traffic simulation in step 8, restart later with `BIZAGENT_RATE_LIMIT=off` if you simulate more than ~40 signups.

## 1. Account
Create an account (name "Asha", any email, password 8+ chars). Expected: you land on "Start with one idea".
Check: sign out, sign in again; a wrong password shows a generic error.

## 2. Add the idea (use exactly this)
| Field | Value |
|---|---|
| Name | Hostel-night snack box |
| What is it? | A weekly box of 8 healthy snacks (roasted chana, fruit bars, makhana, peanut chikki) delivered to hostel and PG rooms for students who skip meals during exam weeks. |
| Who is it for? | Engineering students living in hostels or PGs in Pune |
| Price | INR 399 per week |
| Problem | Mess food closes early; the late-night options are fried snacks or instant noodles. |
| Where | Pune, India |
| Alternatives | Swiggy Instamart and Zepto snacks, the mess canteen, Maggi, doing nothing |

Optional: upload a one-page PDF or Word note about the idea to test document reading.

## 3. Risk scan (1 to 3 min)
Click **Run the risk scan**. Expected: a progress bar moving through five steps, then a ranked list of 4 to 8 assumptions.

What to check (this is the part that needs your judgement):
- Is the **top risk sensible**? For this idea, willingness to pay at INR 399/week against cheap delivery apps is a plausible top risk.
- Open "Why this rating". Does the explanation match the sources? Are sources real and relevant?
- Do **"No usable evidence found"** items show as *Open*, not *Supported*?
- Yellow **Heads up** box: appears if Tavily isn't configured (then no research happens). Remove the Tavily key to see this on purpose.
- Click **Run the scan again**: it should reuse the same assumptions, not duplicate them.

## 4. Design the test
1. **Customer test** tab. Leave the assumption as recommended (or pick willingness to pay). Click **Generate a test kit with AI**.
2. **Setup** tab: read everything critically. Check the claim is falsifiable; the headline is truthful (no invented testimonials or numbers); thresholds are plausible; the contact email is yours.
3. **Edit** to: target **10%**, floor **3%**, minimum visitors **60**, confidence **90%**, deadline **14 days** out. Notice the hint under the target (about 61 visitors).
4. Tick **Also track interview commitment**: target 30%, floor 10%, minimum 5.
5. **Preview page** tab: see the visitor view. **Test kit** tab: read the interview script and outreach drafts.
6. Click **Save draft**.

## 5. Lock (the key moment)
Click **Review and lock**. Try **Lock and go live** with the boxes unticked: it must refuse. Tick both and lock.
Verify:
- The page is live, with a public link, and a fingerprint (64 hex chars) under "Locked rule".
- Go back to the draft via the API/docs or try to change anything: the setup can no longer be edited.

## 6. Be a visitor
Open the public link in a **private window** and on your **phone**.
- Submit with no email, then with no consent box: both show a clear error.
- Sign up properly with a real email. Expect "You're on the list".
- Sign up again with the same email: still shows success, but your dashboard counts it once.
- Add `?s=whatsapp` to the link and sign up from another browser to see source tracking.

## 7. Watch the dashboard
Customer test tab: signups and visitors increase (refresh). Verdict says **Still collecting data**, with how many more visitors are needed.

## 8. Simulate traffic to see every verdict
Fake people, for testing only (never report this as evidence). Use the page link from step 5. Use a **new test** (or delete and recreate the draft) for each scenario, since a locked test can't be edited:
```
python backend/scripts/simulate_traffic.py <page-url> --visitors 60 --signups 12
```
| Visitors / signups | Expected verdict (target 10%, floor 3%, min 60, 90%) |
|---|---|
| 60 / 12 (20%) | **Go** (range 12.9% to 29.7%) |
| 60 / 6 (10%) | Still collecting (range 5.3% to 18.2% straddles the target) |
| 100 / 0 | **Stop** (range 0% to 2.6%, under the 3% floor) |
| 300 / 20 (6.7%) | **Pivot** (range 4.7% to 9.4%, between floor and target) |
| 40 / 30 | Still collecting (below the 60 minimum, however good it looks) |

The last row is the point of the minimum sample: no call from thin data.

## 9. Log conversations
Under **Log a conversation**, add 8 entries: 3 Committed, 2 Interested, 3 Said no. Expect the interview metric to show 37.5% with a very wide range and "Still collecting" (8 conversations can't be decisive; that's honest).
Then **Exclude** one signup with a reason like "Test address". The count drops by one and the reason will appear in the dossier.

## 10. Dossier
Click **Create a shareable dossier**, open the link in a private window. Check: the locked rule and fingerprint, the ruler charts, the exclusion with its reason, and that **no email addresses appear anywhere**. Click **Replace link**: the old link must stop working.

## 11. PDF brief
Click **Download decision brief**. It must download directly (no print dialog) as `hostel-night-snack-box-decision-brief.pdf`. Check: page 1 has the verdict and top 3 risks, page 2 the test and results ruler, page 3 the sources with clickable links. Open it in two different PDF viewers.

## 12. Conclude
Click **Conclude the test**. With enough data it records the result as final; with too little it offers **End early** and records *Inconclusive*. Afterwards: the public page says the test has ended, and the **Decision** tab shows the final verdict.

## 13. Safety checks (5 min, worth doing)
- Create a **second account** in a private window. It must see none of the first account's ideas. Paste the first account's `#/idea/1` URL: expect "not found".
- **Pause** a running test: the public page shows "paused" and signups are refused. **Resume** works.
- Delete the test: the public link must 404 and the signups are gone.
- Stop the server mid-scan and restart: the scan shows as failed with a "start again" message, not spinning forever.

## What to write down for your report
The fingerprint, the counts and intervals, which sources the scan found and whether they were relevant, any wrong or silly risk it ranked, and anything in the AI draft you had to correct. Those corrections are your honest evaluation of the AI part.
