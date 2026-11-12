# Product thinking

## The problem

First-time founders, students and small-business owners decide whether to build something on gut feeling,
friends' encouragement, or an AI chat that says "great idea, here's a plan". None of those is evidence.
What they need is the cheapest honest test of the scariest assumption, run in days, with a result they can't
talk themselves out of.

## The user

Someone with an idea and no budget: a student founder, a side-project builder, a small-business owner thinking
of a new line. They can reach 50 to 300 people (a community, a WhatsApp group, LinkedIn) but can't run a survey
panel. A secondary user is an **incubator or mentor** who gets the read-only dossier and can trust it.

## The flow, and why each step exists

1. **Risk scan.** Founders can't list their own blind spots. The scan lists the assumptions the idea depends on,
   searches for evidence *against* each as hard as for it, and ranks them. It is the on-ramp, not the product.
2. **Customer test.** Desk research can't show demand. A public page and a handful of conversations can.
3. **Pre-registration.** The claim, thresholds, minimum sample and deadline are locked, with a sha256 fingerprint
   and timestamp, before data arrives. This is the borrowed idea from clinical trials: you can't move the goalposts
   after seeing the numbers.
4. **Verdict by rule.** A Wilson interval is compared with your floor and target (see STATS.md). The language
   model never decides whether the evidence passes.
5. **Dossier + brief.** Something a mentor can verify, and a two-page PDF to keep.

## How is this different from asking ChatGPT / Claude / Gemini?

A chat model gives an **opinion** from past text. Biz-Agent runs an **experiment** and keeps the record.
There's no feature a chat can never copy, so the answer is structural:

| A chat can't be... | Biz-Agent is... |
|---|---|
| A neutral party. You can regenerate, rephrase, or re-read weak results until they look good. | Pre-registered. Thresholds are locked and fingerprinted before any data; the verdict is computed. |
| A source of new data. It can only summarise what's on the web or what you paste. | Collecting real responses from people who aren't you, via a public page. |
| Honest about small numbers. "12 signups is a great start!" | Statistical: nothing is called before a minimum sample; ranges are shown, not just percentages. |
| A record others trust. "ChatGPT said it's good" convinces no one. | A read-only dossier showing the locked rule, the counts, every exclusion, and the verdict. |

If asked in a viva: *"ChatGPT generates an opinion from past text. We run a pre-registered experiment with real
customers, collect the data independently of the AI, and compute the verdict statistically. The AI helps design
and analyse the test; it never decides whether the evidence passes."*

An agentic chat tool could host a landing page. The claim is therefore not "we host a page" but **neutral protocol
+ independent data + computed verdict + auditable record**.

## Ethics and data handling (built in, not bolted on)

- The public page states plainly: early test, nothing for sale, no commitment. Consent checkbox is required.
- The creator's name and contact email are on the page (they confirm this at lock) so visitors can request deletion.
- No IPs, no cookies, no analytics: visitors are a salted hash of a browser-generated id; the raw id is never stored.
- Owners can delete a test (and all its data) or their whole account. Dossiers never contain emails and the link can be rotated.
- The product doesn't take payments or promise a product. Don't add a price you wouldn't honour.
- In production you are the data controller for your testers' emails. Add a privacy notice appropriate to your jurisdiction.

## Evaluation plan (for the report / viva)

1. **Live case study.** Run one or two real ideas with 30 to 100 people from your college community.
   Report the locked protocol (with the fingerprint), traffic sources, counts, intervals, and the verdict.
   Real data beats any slide.
2. **Backtest the risk scan.** Take 10 to 15 startups with documented post-mortems (cite them), write each idea as it
   looked at launch, run the scan, and check whether a top-3 risk matches the documented cause
   (`backend/scripts/backtest.py`, template in `evaluation/`). Include a few successes to check it doesn't rate everything critical.
   Caveats to state: small n, hindsight bias in tagging causes, possible leakage (the post-mortem may be searchable).
3. **Direct comparison.** Give a chat model the same idea; put its answer next to the product's output and show
   what the chat cannot produce: a locked rule, real signals, a computed verdict, an auditable record.
4. **Verdict-engine tests.** The simulated cases in `tests/test_stats.py` and `tests/test_sprints.py`.

## Known weaknesses (say them before the examiner does)

- Waitlist conversion over-states demand. Mitigation: the supporting "interview commitment" metric and the next-step
  guidance to raise the commitment after a Go.
- A small, friendly audience (classmates) biases results upward. The dossier shows traffic sources so a reader can judge.
- Early looks at the data inflate false positives. The UI labels pre-deadline readings and the rule never calls before the minimum sample.
- Thresholds suggested by the AI are assumptions, not benchmarks; the product labels them as such.
- Cross-user benchmarks (typical conversion by niche) would be a genuine moat but need real usage first; it's roadmap, not a claim.
