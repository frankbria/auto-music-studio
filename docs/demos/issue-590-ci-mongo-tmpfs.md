# #590: CI integration Mongo on tmpfs

*2026-10-01T02:35:40Z by Showboat 0.6.1*
<!-- showboat-id: 418db96c-4fbf-45f1-9635-1eac2c3cc2ce -->

**Problem.** `ci (3.12)` sometimes ran its integration step for 30–40 minutes and hit the 45-minute job limit. **Claim.** The cost is mongod's disk, not Python: each integration test builds ~21 collections and ~74 indexes and then drops them. Putting mongod's data dir on tmpfs removes the disk from that path.

Acceptance criterion: *`ci (3.12)` stays well under its limit on a slow runner. Show p95 job durations from ~20 runs before and after.*

## 1. The change reaches the runner

The CI service config, and the `docker create` line GitHub logged for the PR's `ci (3.12)` job (run 36803057884):

```bash
python3 -c "import yaml;print(yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']['ci']['services']['mongodb']['options'])"
jid=$(gh api repos/frankbria/auto-music-studio/actions/runs/36803057884/jobs --jq '.jobs[]|select(.name=="ci (3.12)")|.id')
gh api repos/frankbria/auto-music-studio/actions/jobs/$jid/logs | grep -m1 -o 'docker create .*--tmpfs /data/db:size=2g'| sed 's/--name [^ ]* --label [^ ]* --network [^ ]* //'
```

```output
--tmpfs /data/db:size=2g --health-cmd "mongosh --quiet --eval 'db.adminCommand(\"ping\")'" --health-interval 10s --health-timeout 5s --health-retries 5
docker create --network-alias mongodb -p 27017:27017 --tmpfs /data/db:size=2g
```

## 2. Mechanism: mongod's slow ops, before vs after

mongod logs every op that takes ≥100 ms. Below, the same workload on four jobs: a slow and a fast job from `main` before the change (run 36649056721), and two `ci (3.12)` jobs on this branch.

```bash
for spec in 36649056721:'ci (3.12)':before-slow 36649056721:'ci (3.11)':before-fast 36803057884:'ci (3.12)':after 36802457806:'ci (3.12)':after; do
  IFS=: read rid leg tag <<<"$spec"
  jid=$(gh api repos/frankbria/auto-music-studio/actions/runs/$rid/jobs --jq ".jobs[]|select(.name==\"$leg\")|.id")
  log=$(gh api repos/frankbria/auto-music-studio/actions/jobs/$jid/logs)
  printf '%-12s %-10s run %s  slow createIndexes: %5s  integration: %s\n' "$tag" "$leg" $rid \
    "$(grep '"Slow query"' <<<"$log" | grep -c '"command":{"createIndexes"')" \
    "$(grep -o '[0-9]* passed.* in [0-9.]*s ([0-9:]*)' <<<"$log" | tail -1 | grep -o '([0-9:]*)')"
done
```

```output
before-slow  ci (3.12)  run 36649056721  slow createIndexes:  4391  integration: (0:29:38)
before-fast  ci (3.11)  run 36649056721  slow createIndexes:    21  integration: (0:07:07)
after        ci (3.12)  run 36803057884  slow createIndexes:     5  integration: (0:05:58)
after        ci (3.12)  run 36802457806  slow createIndexes:     8  integration: (0:10:48)
```

## 3. Acceptance: job durations, ~20 runs a side and more

**Before:** the last 45 `ci` runs on `main` and PRs up to 2026-09-30. **After:** 20 runs of this branch (19 `workflow_dispatch` + the PR run). Jobs cancelled by a newer push are excluded; the one killed at the 45-minute limit is kept.

```python3
import json, statistics as st, subprocess
from datetime import datetime
SETS = {"before": "36658639374 36657123536 36657090191 36656880810 36655371168 36655280074 36653918422 36653760570 36652244349 36652152706 36649172812 36649056721 36648949282 36647814519 36647523132 36647413098 36647314557 36644384179 36642239377 36556196400 36555195656 36553103882 36550733582 36546220446 36545717411 36545561569 36543921102 36543125986 36542077325 36542072269 36541999010 36541906285 36541815699 36541694063 36521776490 36520100180 36518521525 36516923361 36515283641 36514364078 36505964751 36504474997 36502530805 36502515272 36502390946 ".split(), "after": "36804422950 36804421112 36804419110 36804416849 36804414976 36804412768 36804410899 36804408928 36804406712 36804404600 36803057884 36802463199 36802461536 36802459668 36802457806 36802456095 36802454224 36802452381 36802450703 36802448886 ".split()}
def mins(a, b): return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 60
def p95(xs): xs = sorted(xs); k = (len(xs) - 1) * 0.95; f = int(k); return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)
print(f"{'set':7}{'leg':11}{'n':>3}{'median':>8}{'p95':>7}{'max':>7}   integration p95 / max (min)")
for name, ids in SETS.items():
    jobs = [j for r in ids for j in json.loads(subprocess.check_output(["gh", "api", f"repos/frankbria/auto-music-studio/actions/runs/{r}/jobs"]))["jobs"] if j["name"].startswith("ci (")]
    for leg in ("ci (3.11)", "ci (3.12)"):
        dur, integ = [], []
        for j in jobs:
            if j["name"] != leg or not j["completed_at"]: continue
            d = mins(j["started_at"], j["completed_at"])
            if j["conclusion"] != "success" and d < 44: continue
            dur.append(d)
            s = [s for s in j["steps"] if s["name"].startswith("Integration") and s["completed_at"]]
            if s: integ.append(mins(s[0]["started_at"], s[0]["completed_at"]))
        print(f"{name:7}{leg:11}{len(dur):>3}{st.median(dur):>8.1f}{p95(dur):>7.1f}{max(dur):>7.1f}   {p95(integ):.1f} / {max(integ):.1f}")
```

```output
set    leg          n  median    p95    max   integration p95 / max (min)
before ci (3.11)   41    17.4   19.5   22.6   14.2 / 17.0
before ci (3.12)   42    18.1   35.0   45.2   29.5 / 39.8
after  ci (3.11)   20    14.1   16.6   17.3   11.0 / 11.5
after  ci (3.12)   20    15.0   16.4   16.6   10.8 / 11.0
```

## 4. Slow disk, same tests, with and without tmpfs

Is the speed-up just luck in which runners we drew? To check, run one integration file against two local mongo:7 containers on this machine's (slow, WSL) disk: one disk-backed, one with CI's exact tmpfs option.

```bash
U='--ulimit nofile=64000:64000'
docker run -d --rm --name d590-disk $U -p 27031:27017 mongo:7 >/dev/null
docker run -d --rm --name d590-tmpfs $U --tmpfs /data/db:size=2g -p 27032:27017 mongo:7 >/dev/null
for c in d590-disk d590-tmpfs; do until docker exec $c mongosh --quiet --eval 'db.adminCommand("ping")' >/dev/null 2>&1; do sleep 1; done; done
for c in d590-disk d590-tmpfs; do echo "$c: $(docker exec $c sh -c 'mount | grep " /data/db " | cut -d" " -f1,5')"; done
for p in 27031 27032; do echo "port $p: $(ACEMUSIC_TEST_MONGODB_URL=mongodb://localhost:$p uv run pytest tests/test_credit_refunds.py -m integration --no-cov -q 2>&1 | tail -1 | grep -o '[0-9]* passed.*')"; done
docker stop d590-disk d590-tmpfs >/dev/null
```

```output
d590-disk: /dev/sdd ext4
d590-tmpfs: tmpfs tmpfs
port 27031: 38 passed in 61.19s (0:01:01)
port 27032: 38 passed in 5.17s
```

## Verdict

| Criterion | Evidence | Status |
|---|---|---|
| `ci (3.12)` stays well under its 45 min limit on a slow runner | 3.12 job p95 **35.0 → 16.4 min**, max **45.2 → 16.6** (42 jobs before, 20 after). Integration p95 29.5 → 10.8. | VERIFIED |
| …and the gain isn't just runner luck | The slow job logged 4,391 slow `createIndexes` ops. After the change, jobs logged 5–8. On a slow local disk the same 38 tests took 61 s disk-backed vs 5 s on tmpfs. | VERIFIED |
| tmpfs config actually applied in CI | GitHub's `docker create` line carries `--tmpfs /data/db:size=2g` | VERIFIED |

Caveat: the 20 after-runs can't guarantee one landed on a slow-disk runner (before, ~1 in 10 3.12 jobs did). Sections 2 and 4 cover that case directly.
