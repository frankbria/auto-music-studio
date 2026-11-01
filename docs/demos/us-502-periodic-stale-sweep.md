# #502 The stale-job sweep runs periodically

*2026-11-01T01:38:00Z by Showboat 0.6.1*
<!-- showboat-id: 1e427696-f896-41b7-b9a5-5c6d87313021 -->

Live run against a throwaway `acemusic_demo_502` database on the local mongod. A real `JobProcessor` starts with `stale_after=60s` and `sweep_interval=1s`, and `concurrency=0` so it never re-claims what it re-queues. Two `processing` video jobs are inserted *after* startup: one whose heartbeat stopped 120s ago (a crashed sibling), and one heartbeating 1s ago (a live sibling). Before #502 only a restart re-ran the sweep.

```bash
uv run python $DEMO/sweep_demo.py 2>&1 | grep -v INFO
```

```output
processor started; startup sweep done
after start: orphaned = processing | live = processing
2.5s later:  orphaned = queued | live = processing
```
