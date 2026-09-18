# Issue #499 — plugin third-party notices

*2026-09-18T21:08:22Z*

AC1: every CI package carries THIRD_PARTY_NOTICES.md. Replay of the workflow's Package step against a local Linux Release build:

```bash
cd plugin && vst3=$(find build -maxdepth 6 -name "*.vst3" | head -1) && mkdir -p dist && cp -R "$vst3" dist/ && cp THIRD_PARTY_NOTICES.md dist/ && ls -1 dist && cmp THIRD_PARTY_NOTICES.md dist/THIRD_PARTY_NOTICES.md && echo "notices packaged, byte-identical"; rm -rf dist
```

```output
AceMusic Studio.vst3
THIRD_PARTY_NOTICES.md
notices packaged, byte-identical
```

AC2: every compiled-in component is present in the shipped binary and has a notice section. Evidence from the built VST3's strings, then the notices headings:

```bash
so=$(find plugin/build -path "*VST3*" -name "*.so" | head -1); strings -a "$so" | grep -m1 "reference libFLAC"; strings -a "$so" | grep -m1 "Xiph.Org libVorbis"; strings -a "$so" | grep -m1 "in IHDR"; echo "harfbuzz symbols: $(strings -a "$so" | grep -c hb_)"; find plugin/build -path "*AceMusicPlugin.dir*" -name "juce_graphics_Sheenbidi*.o" -o -path "*AceMusicPlugin.dir*" -name "juce_graphics_Harfbuzz*.o" | sed "s#.*/##"; grep "^## " plugin/THIRD_PARTY_NOTICES.md
```

```output
reference libFLAC 1.4.3 20230623
Xiph.Org libVorbis I 20200704 (Reducing Environment)
Image width is zero in IHDR
harfbuzz symbols: 845
juce_graphics_Sheenbidi.c.o
juce_graphics_Harfbuzz.cpp.o
## What is compiled in
## Steinberg VST3 SDK (3.8.0)
## JUCE Framework (8.0.14)
## FLAC
## Ogg Vorbis
## libpng
## Independent JPEG Group (jpeglib)
## zlib
## HarfBuzz
## SheenBidi
## Apple AudioUnitSDK (macOS AU build only)
## Apache License 2.0
## Not compiled into this build
```

Licence bodies are verbatim JUCE 8.0.14 texts (whitespace-normalised substring check against the bundled files):

```bash
uv run python - <<EOF
import re
from pathlib import Path
J = Path.home() / ".cache/juce/JUCE-8.0.14/modules"
notices = Path("plugin/THIRD_PARTY_NOTICES.md").read_text()
blocks = re.findall(r"\`\`\`\n(.*?)\`\`\`", notices, re.S)
srcs = ["juce_audio_formats/codecs/flac/Flac Licence.txt", "juce_audio_formats/codecs/oggvorbis/Ogg Vorbis Licence.txt", "juce_graphics/image_formats/pnglib/LICENSE", "juce_graphics/image_formats/jpglib/README", "juce_core/zip/zlib/zlib.h", "juce_graphics/fonts/harfbuzz/COPYING", "juce_graphics/unicode/sheenbidi/LICENSE"]
norm = lambda s: " ".join(s.split())
corpus = [norm((J / s).read_text(errors="replace")) for s in srcs]
for b in blocks[1:]:
    print(norm(b)[:40].ljust(42), "verbatim" if any(norm(b) in c for c in corpus) else "MISMATCH")
EOF
```

```output
libFLAC - Free Lossless Audio Codec libr   verbatim
Copyright (c) 2002-2020 Xiph.org Foundat   verbatim
COPYRIGHT NOTICE, DISCLAIMER, and LICENS   verbatim
In legalese: The authors make NO WARRANT   verbatim
Copyright (C) 1995-2024 Jean-loup Gailly   verbatim
HarfBuzz is licensed under the so-called   verbatim
Apache License Version 2.0, January 2004   verbatim
```

AC3: components JUCE bundles but this build does not compile are listed as excluded:

```bash
sed -n "/^## Not compiled/,\$p" plugin/THIRD_PARTY_NOTICES.md
```

```output
## Not compiled into this build

JUCE bundles these too, but this build does not compile them, so they need no notice.
Re-audit this file if any of them is ever switched on.

- **ASIO SDK** (Steinberg proprietary / GPLv3) — only built with `JUCE_ASIO=1`, which
  this build never sets. See `LICENSE.md` before changing that.
- **AAX SDK** (Avid proprietary / GPLv3) — AAX is not in `FORMATS`.
- **LV2 SDK** (ISC) — neither an LV2 plug-in format nor LV2 hosting
  (`JUCE_PLUGINHOST_LV2`) is enabled.
- **Oboe** (Apache 2.0) — Android only.
- **GLEW, Mesa, Khronos headers** (BSD / MIT) — in `juce_opengl`, which is not linked.
- **CHOC and QuickJS** (ISC / MIT) — in `juce_javascript`, which is not linked.
- **Box2D** (zlib) — in `juce_box2d`, which is not linked.
```

Guard tests (fail if a section, the IJG statement, the Apache text, an exclusion, or the packaging step is removed — each mutation was verified to fail):

```bash
uv run pytest tests/test_plugin_notices.py -q --no-cov -p no:cacheprovider 2>&1 | tail -1
```

```output
[32m[32m[1m5 passed[0m[32m in 0.03s[0m[0m
```
