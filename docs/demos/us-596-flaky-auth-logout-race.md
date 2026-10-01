# Issue #596: deterministic logout-race test

*2026-10-01T17:50:17Z by Showboat 0.6.1*
<!-- showboat-id: 43c953e0-c4b9-4d26-a440-98baf646c352 -->

The CI failure was `expected 1 to be 2` at `waitFor(() => expect(call).toBe(2))`. The visibility listener effect re-subscribes on `[accessToken, refresh]`. On a slow runner React's scheduler yields between the DOM commit, which `waitFor` observes, and the passive effect, so the event reached the stale signed-out listener. The harness below simulates a slow runner: it spies `performance.now` to advance 10ms per call, which forces the scheduler to yield every slice. It then runs the test N times.

**Criterion 1 (before):** the test as it was on main fails under slow-runner pressure with the same error as CI.

```bash
/tmp/claude-1000/-home-frankbria-projects-auto-music-studio/09fef162-3494-45af-8f39-c59ea68334e9/scratchpad/slow-run.sh origin/main 6
```

```output
      1 Tests  1 passed
      5 expected 1 to be 2
```

**Criterion 1 (after):** the fixed test settles the mount inside act, so the listener is re-subscribed before dispatch. It passes on every run under the same pressure.

```bash
/tmp/claude-1000/-home-frankbria-projects-auto-music-studio/09fef162-3494-45af-8f39-c59ea68334e9/scratchpad/slow-run.sh HEAD 10
```

```output
     10 Tests  1 passed
```

**Criterion 2:** no waitFor timeout was raised (count of `timeout:` in the diff is 0). The fix removes the wall-clock wait on `call` altogether.

```bash
git diff origin/main...HEAD -- web/contexts/auth-context.test.tsx | grep -E '^[-+] ' ; git diff origin/main...HEAD | grep -c 'timeout:' || true
```

```output
-    await waitFor(() =>
-      expect(screen.getByTestId("state")).toHaveTextContent("in:")
-    )
+    // Settle the mount refresh inside act so React also flushes the effect that
+    // re-subscribes the visibility listener with the restored token. A waitFor
+    // on the DOM can resolve between that commit and its effects on a slow
+    // runner, leaving the event to hit the stale signed-out listener (#596).
+    await act(async () => {
+      await new Promise((resolve) => setTimeout(resolve, 0))
+    })
+    expect(screen.getByTestId("state")).toHaveTextContent("in:")
-    await waitFor(() => expect(call).toBe(2))
+    expect(call).toBe(2)
0
```

**Criterion 3 (mutation):** each guard is removed one at a time, the fixed test is run, and the guard is restored. Every mutation must turn the test red.

```bash
cd web; f=contexts/auth-context.tsx; for m in 's/    refreshAbort.current?.abort()$/    \/\/ abort removed/' 's/        if (sessionEpoch.current !== epoch) return null/        \/\/ epoch guard removed/' 's/      refresh()$/      \/\/ visibility refresh removed/'; do sed -i "$m" $f; git diff $f | grep '^+ ' ; npx vitest run contexts/auth-context.test.tsx -t resurrect 2>&1 | grep -E 'Tests  1|Error: ' | head -2 ; git checkout -q $f; done; git status --short $f
```

```output
+    // abort removed
AssertionError: expected false to be true // Object.is equality
      Tests  1 failed | 7 skipped (8)
+        // epoch guard removed
Error: [2mexpect([22m[31melement[39m[2m).toHaveTextContent()[22m
      Tests  1 failed | 7 skipped (8)
+      // visibility refresh removed
AssertionError: expected 1 to be 2 // Object.is equality
      Tests  1 failed | 7 skipped (8)
```

**Harness:** `slow-run.sh <git-ref> <runs>`, kept in the session scratchpad and reproduced here:

```bash
#!/usr/bin/env bash
# Usage: slow-run.sh <git-ref> <runs>
# Runs the logout-race test from <git-ref> with performance.now advancing 10ms
# per call, which makes React's scheduler yield between commit and effects.
set -u
cd /home/frankbria/projects/ams-596/web
git show "$1:web/contexts/auth-context.test.tsx" | python3 -c '
import sys
src = sys.stdin.read()
src = src.replace("afterEach(() => vi.unstubAllGlobals())",
  "afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })\nbeforeEach(() => { let t = 0; vi.spyOn(performance, \"now\").mockImplementation(() => (t += 10)) })")
src = src.replace("import { afterEach, describe", "import { afterEach, beforeEach, describe")
open("contexts/zz-slow.test.tsx", "w").write(src)
'
for i in $(seq "$2"); do
  npx vitest run contexts/zz-slow.test.tsx -t resurrect 2>&1 | grep -oE "expected [0-9a-z]+ to be [0-9a-z]+|Tests  1 (passed|failed)" | head -1
done | sort | uniq -c
rm -f contexts/zz-slow.test.tsx
```
