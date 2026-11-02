# #695: Pro and Enterprise plans, monthly or annual


| Plan | Monthly | Annual | Credits/month | Beyond Pro |
|---|---|---|---|---|
| Free | $0 | | 50 | |
| Pro | $24 | $228 ($19/mo) | 500 | |
| Enterprise | $99 | $998 (about $83/mo) | 2,500 | 4K video, priority job queue |

- **Tiers.** `enterprise` joins `free` and `pro`. Anything else still fails closed to free. Enterprise has every Pro capability plus the new `VIDEO_4K`, and a Pro account asking for 4K gets a 403 naming Enterprise.
- **Checkout.** `POST /billing/checkout {plan, interval}` uses the configured Price for that pair and records the plan in the session metadata; with no body it's Pro monthly, as before. `ACEMUSIC_API_STRIPE_MANAGED_PAYMENTS=true` adds `managed_payments[enabled]`, and top-up packs then carry a tax code. `GET /billing/plans` serves prices, credits and per-interval availability.
- **Webhooks.** A completed checkout grants the plan in its metadata. A subscription update reads the tier from the subscription's Price, so a plan change in the billing portal lands on the right tier.
- **Priority queue.** `Job.priority` is set from the owner's tier when the job is inserted, and the processor claims by priority, then age.
- **Web.** The billing page shows Free, Pro and Enterprise with a Monthly/Annual toggle and starts checkout for the chosen plan. Enterprise unlocks everything Pro does, and 4K is shown as Enterprise-only.

## Evidence

```bash
uv run pytest -m integration tests/test_billing_api.py -k TestPlans -q --no-cov 2>&1 | tail -1
```

```output
8 passed, 53 deselected, 2 warnings in 3.48s
```

```bash
uv run pytest -m integration tests/test_tier_enforcement_api.py -k "4k or up_to_1080p" -q --no-cov 2>&1 | tail -1
```

```output
4 passed, 47 deselected, 1 warning in 3.10s
```

```bash
uv run pytest -m integration tests/test_job_processor.py -k enterprise_job -q --no-cov 2>&1 | tail -1
```

```output
1 passed, 30 deselected in 2.94s
```

```bash
cd web && npx vitest run components/settings/BillingSettings.test.tsx components/video/VideoForm.test.tsx lib/billing.test.ts hooks/use-subscription-tier.test.tsx 2>&1 | grep -E "Tests "
```

```output
      Tests  44 passed (44)
```
