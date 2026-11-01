# #597 MIDI transcription without TensorFlow (keras/protobuf alerts cleared)

*2026-11-01T02:30:28Z by Showboat 0.6.1*
<!-- showboat-id: a4b4ac09-f002-4dfb-81b3-aaf72face139 -->

basic-pitch 0.4.0 declares `tensorflow<2.15.1` on Linux, which pinned keras 2.14 and protobuf 4 with their open advisories. A uv override drops TensorFlow, and basic-pitch falls back to its bundled ONNX model through `onnxruntime`.

## 1. The lockfile no longer contains TensorFlow, keras or tensorboard, and protobuf is patched

```bash
for p in tensorflow keras tensorboard protobuf onnxruntime; do printf '%-12s ' $p; grep -A1 "^name = \"$p\"$" uv.lock | sed -n 2p || true; echo; done | sed 's/version = //' | awk 'NF==1{print $1" (not in uv.lock)"; next}{print}'
```

```output
tensorflow (not in uv.lock)
keras (not in uv.lock)
tensorboard (not in uv.lock)
protobuf     "7.36.2"

onnxruntime  "1.31.1"

```

## 2. `uv sync --extra audio-ml-midi` installs, and transcription works end to end

```bash
uv sync -q --extra dev --extra audio-ml-midi && uv run python $DEMO/transcribe.py 2>&1 | grep -viE 'warn|pkg_resources|Predicting'
```

```output
basic-pitch model: nmp.onnx
tensorflow is not installed
keras is not installed
notes per part: {'melody': 0, 'chords': 1, 'bass': 0, 'drums': 1}
pitches found: [36, 69] (A4 = 69)
```
