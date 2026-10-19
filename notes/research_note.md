# The crypto funding carry: what it really earns, when, and what breaks it

*Research note. Fill this in from `reports/BTC` and `reports/ETH`. Aim for
3–5 pages with charts; page 1 alone should give the conclusion.*

## 1. Summary (5 lines max)

- Net return on capital of the passive carry, BTC and ETH, after costs:
- Best variant and why:
- Main risk:
- How the trade has changed over time (crowding, ETF and institutional basis buyers):
- What I would do with real capital:

## 2. Data

- Venues, coins, period, settlement intervals
- Sanity checks: gaps, duplicate settlements, venue history start dates
- Table: mean APR by venue and year (`apr_by_year.csv`)

## 3. Funding behaviour

- Rolling 30d funding by venue: common factor vs venue-specific
- Share of negative settlements; worst 30d periods and what happened in the market then
- Regime table: is high funding followed by high funding? relation to spot returns
- Cross-venue dispersion: size, persistence, which venue is structurally high and why (user base, leverage, collateral)

## 4. Strategy results

| Strategy | APR on capital | Sharpe | Max DD | Time invested | Funding | Basis | Costs |
|---|---|---|---|---|---|---|---|
| Always on | | | | | | | |
| Threshold | | | | | | | |
| Cross-venue | | | | | | | |

- Sensitivity: entry/exit thresholds, lookback, fees (taker vs maker entry)
- Where the costs go; break-even funding level for a round trip

## 5. Risk

- Liquidation table: leverage you can safely run and how often you must rebalance
- Basis blowouts around liquidation cascades (premium during the worst days)
- Counterparty risk: how much capital sits on each venue, and the FTX lesson

## 6. Conclusion and what a desk would do differently

## 7. Limitations
