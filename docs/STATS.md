# Verdict statistics

All logic lives in `backend/app/services/stats.py` (pure functions, no LLM) and is covered by `tests/test_stats.py`.

## Interval

For `k` successes in `n` trials, a **Wilson score interval** `[lo, hi]` at confidence 80%, 90% or 95%.
Wilson behaves well at small `n` and extreme rates, unlike the normal approximation (which can go below 0%).

## Decision rule for one metric

Pre-registered inputs: `success_rate` (target), `failure_rate` (floor, lower than target), `min_sample`, `confidence`.

| Condition (checked in order) | Verdict |
|---|---|
| `n < min_sample` | keep running (inconclusive once the test has finished) |
| `lo >= target` | **go** |
| `hi < floor` | **stop** |
| `lo >= floor` and `hi < target` | **pivot** (credibly between: some pull, below target) |
| otherwise (interval straddles a threshold) | keep running (inconclusive once finished) |

"Finished" = the deadline passed or the owner ended the test.

## Two metrics

- `waitlist_conversion`: non-excluded signups / unique visitors (a signup always counts as a visit).
- `interview_commitment`: conversations that ended in a concrete commitment / conversations logged.
  "Interested" does not count as success.

The **primary** metric decides. A `go` is downgraded to `pivot` if a supporting metric is credibly at `stop`.
Hard floors for `min_sample`: 30 (waitlist), 5 (interviews).

## Sample-size hint

`suggested_min_sample(target, confidence)` returns the smallest `n` at which an observed rate 50% above target would
yield `lo >= target`. It is a planning hint, not a power guarantee. For a 10% target at 90% confidence it is 61.
The AI never sets sample sizes; code computes them.

## Caveats the product states

- **Peeking.** Looking repeatedly and stopping at the first favourable reading inflates false positives. The rule requires
  the minimum sample, and pre-deadline results are labelled early.
- **Waitlist != willingness to pay.** Hence the commitment metric and the next-step text.
- **Independence.** Visitors are counted once per browser, signups once per email. Determined fakers can still inflate numbers;
  owners can exclude entries (permanently, with a public reason), which are disclosed in the dossier.
- **Selection.** The sample is whoever you sent to the page. The dossier shows traffic sources.

## Worked example

Target 10%, floor 3%, min sample 30, 90% confidence. 12 signups of 34 visitors: rate 35.3%, interval 23.4% to 49.4%.
`lo (23.4%) >= 10%` and `n >= 30`, so **go**.
Had it been 3 of 34 (8.8%, interval 3.6% to 20.1%), the interval straddles the target: **keep running**.
