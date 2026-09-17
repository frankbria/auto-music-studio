# Issue #422: refunds return credit to the bucket that paid for it

*2026-09-15T04:21:56Z*

Credits live in two buckets: a **monthly** allowance that the anniversary reset tops *up to* the tier allocation, and **purchased** credits that never expire. Charges spend monthly first. Before this fix every refund landed in the monthly bucket, so purchased credit came back as expiring allowance and suppressed the next monthly grants. Each step below runs the real service layer against a local throwaway MongoDB.

## AC1 — a refund returns credits to the bucket(s) the charge took them from

The scenario from the issue: free tier (50/month), the musician buys the 100-pack, then spends 120 on a batch.

```bash
uv run python docs/demos/issue-422-refund-buckets.py reset && uv run python docs/demos/issue-422-refund-buckets.py charge-120
```

```output
start                        monthly=50  purchased=100  spendable=150
after 120-credit charge      monthly=0  purchased=30  spendable=30
ledger rows for this job (amount / purchased_amount):
  song           amount=-120  purchased_amount=-70  balance_after=30
```

The charge row records that 70 of the 120 came from the purchased bucket. The batch fails and the processor refunds it:

```bash
uv run python docs/demos/issue-422-refund-buckets.py fail-and-refund
```

```output
after refund                 monthly=50  purchased=100  spendable=150
ledger rows for this job (amount / purchased_amount):
  song           amount=-120  purchased_amount=-70  balance_after=30
  song_refund    amount=+120  purchased_amount=+70  balance_after=150
```

Both buckets are back exactly where they started: 50 monthly, 100 purchased. Under the old behaviour this read `monthly=120 purchased=30`. To prove the monthly grant is no longer suppressed, spend 10 this month and roll the anniversary forward:

```bash
uv run python docs/demos/issue-422-refund-buckets.py anniversary
```

```output
spent 10 this month          monthly=40  purchased=100  spendable=140
after monthly reset          monthly=50  purchased=100  spendable=150
monthly_reset granted: 10
```

The reset grants the 10 back up to the 50 allocation. With the old `monthly=120` the grant would have been `max(0, 50 - 110) = 0` and the musician would hold 110 expiring credits they had paid for.

## AC2 — a charge funded entirely from the monthly allowance refunds as monthly

A 20-credit charge against 50 monthly never touches the purchased bucket, so its refund must not either (`purchased_amount=+0`).

```bash
uv run python docs/demos/issue-422-refund-buckets.py monthly-only
```

```output
after 20-credit charge       monthly=30  purchased=100  spendable=130
after refund                 monthly=50  purchased=100  spendable=150
ledger rows for this job (amount / purchased_amount):
  song           amount=-20  purchased_amount=-0  balance_after=130
  song_refund    amount=+20  purchased_amount=+0  balance_after=150
```

## AC3 — a charge spanning both buckets refunds proportionally

3 credits charged: 1 from monthly, 2 from purchased. A handler refunds half (1.5), as the full-song chain does for unperformed sections: 0.5 goes back to monthly and 1.0 to purchased.

```bash
uv run python docs/demos/issue-422-refund-buckets.py partial
```

```output
after 3-credit charge        monthly=0  purchased=8  spendable=8
after refunding half         monthly=0.5  purchased=9  spendable=9.5
ledger rows for this job (amount / purchased_amount):
  full_song      amount=-3  purchased_amount=-2  balance_after=8
  full_song_refund amount=+1.5  purchased_amount=+1  balance_after=9.5
```

## AC4 — a partially-refunded job cannot be refunded from the purchased bucket twice

4 credits charged (1 monthly, 3 purchased). A handler refunds 2 (proportionally 0.5 + 1.5), then the generic failed-job refund runs twice. The purchased bucket receives its 3 back exactly once and the second processor refund is a no-op.

```bash
uv run python docs/demos/issue-422-refund-buckets.py no-double-refund
```

```output
after 4-credit charge        monthly=0  purchased=7  spendable=7
handler refunded 2           monthly=0.5  purchased=8.5  spendable=9
processor refund #1          monthly=1  purchased=10  spendable=11
processor refund #2          monthly=1  purchased=10  spendable=11
ledger rows for this job (amount / purchased_amount):
  full_song      amount=-4  purchased_amount=-3  balance_after=7
  full_song_refund amount=+2  purchased_amount=+1.5  balance_after=9
  full_song_refund amount=+2  purchased_amount=+1.5  balance_after=11
```

## AC5 — the existing refund tests still pass without asserting on a single field

The pre-existing refund and bucket suites run unchanged (they assert on `spendable()`, both buckets together), alongside the new `TestRefundBuckets` cases.

```bash
ACEMUSIC_TEST_MONGODB_URL=mongodb://localhost:27018 uv run pytest tests/test_credit_refunds.py tests/test_credit_buckets.py -m integration -q --no-cov -p no:cacheprovider 2>&1 | tail -3
```

```output
......................................................                   [100%]
54 passed in 170.09s (0:02:50)
```
