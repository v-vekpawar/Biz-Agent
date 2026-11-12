# Backtest cases

Build `cases.json` from 10 to 15 startups whose failure (or success) reasons are documented in
public post-mortems. Use only facts you can cite: write the idea as it looked at launch, and tag
the documented failure causes with these categories:

`customer_problem`, `market_demand`, `competition_alternatives`, `willingness_to_pay`, `pricing`,
`distribution_acquisition`, `unit_economics`, `operations`, `technology_feasibility`,
`legal_regulatory`, `other`

Then run `python backend/scripts/backtest.py evaluation/cases.json --email ... --password ...`.
Report the hit rate together with the caveats: small n, hindsight bias in the categorisation,
and that web search results for a launch-era idea may already contain the post-mortem (leakage).
Include a few startups that succeeded and check the scan does not rate everything critical.
