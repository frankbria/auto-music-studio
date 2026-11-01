# #646 Stripe webhooks in the post-basil shape

*2026-11-01T01:20:46Z by Showboat 0.6.1*
<!-- showboat-id: b663bb78-cd5e-4422-aca5-400a3312db82 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_646` database), started with a Stripe webhook secret. Events are signed with Stripe's real scheme (`t=…,v1=HMAC-SHA256`) by a small script and posted to `/api/v1/billing/webhook`. The payloads use the shape Stripe sends since API version 2025-03-31.basil: an invoice names its subscription under `parent.subscription_details`, and the period end is on the subscription's items. The seeded musician is a Pro subscriber (`cus_demo` / `sub_demo`).

## 1. A subscription update stores the period end from its items

```bash
. $DEMO/env.sh >/dev/null; export WHSEC=whsec_demo646; python3 $DEMO/post_event.py customer.subscription.updated '{"id":"sub_demo","object":"subscription","customer":"cus_demo","status":"active","cancel_at_period_end":false,"items":{"object":"list","data":[{"id":"si_1","current_period_end":1800000000}]}}' evt_sub_1; M "db.users.findOne({_id: ObjectId('$USER_ID')}, {_id: 0, subscription_status: 1, subscription_tier: 1, subscription_current_period_end: 1})"
```

```output
HTTP 200 {"status":"pro"}
{
  subscription_tier: 'pro',
  subscription_status: 'active',
  subscription_current_period_end: ISODate('2027-01-15T08:00:00.000Z')
}
```

## 2. A failed subscription invoice sets past_due (it used to be recorded as a one-off)

```bash
. $DEMO/env.sh >/dev/null; export WHSEC=whsec_demo646; python3 $DEMO/post_event.py invoice.payment_failed '{"customer":"cus_demo","parent":{"type":"subscription_details","subscription_details":{"subscription":"sub_demo"}},"amount_due":1000,"currency":"usd","status":"open"}' evt_inv_failed; M "db.users.findOne({_id: ObjectId('$USER_ID')}, {_id: 0, subscription_status: 1, subscription_tier: 1, subscription_current_period_end: 1})"
```

```output
HTTP 200 {"status":"past_due"}
{
  subscription_tier: 'pro',
  subscription_status: 'past_due',
  subscription_current_period_end: ISODate('2027-01-15T08:00:00.000Z')
}
```

## 3. The paid retry clears it

```bash
. $DEMO/env.sh >/dev/null; export WHSEC=whsec_demo646; python3 $DEMO/post_event.py invoice.paid '{"customer":"cus_demo","parent":{"type":"subscription_details","subscription_details":{"subscription":"sub_demo"}},"amount_paid":1000,"currency":"usd","status":"paid"}' evt_inv_paid; M "db.users.findOne({_id: ObjectId('$USER_ID')}, {_id: 0, subscription_status: 1, subscription_tier: 1, subscription_current_period_end: 1})"
```

```output
HTTP 200 {"status":"paid"}
{
  subscription_tier: 'pro',
  subscription_status: 'active',
  subscription_current_period_end: ISODate('2027-01-15T08:00:00.000Z')
}
```

## 4. A credit top-up (no subscription parent) is still a one-off and leaves the subscription alone

```bash
. $DEMO/env.sh >/dev/null; export WHSEC=whsec_demo646; python3 $DEMO/post_event.py invoice.paid '{"customer":"cus_demo","amount_paid":500,"currency":"usd","status":"paid"}' evt_topup; M "db.users.findOne({_id: ObjectId('$USER_ID')}, {_id: 0, subscription_status: 1, subscription_tier: 1, subscription_current_period_end: 1})"
```

```output
HTTP 200 {"status":"one_off"}
{
  subscription_tier: 'pro',
  subscription_status: 'active',
  subscription_current_period_end: ISODate('2027-01-15T08:00:00.000Z')
}
```
