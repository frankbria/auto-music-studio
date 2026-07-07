import { describe, expect, it } from "vitest"

import type { ClipAudio } from "@/lib/audio-peaks"
import { encodeWav } from "@/lib/wav-encode"

function ascii(view: DataView, offset: number, length: number): string {
  let s = ""
  for (let i = 0; i < length; i++) s += String.fromCharCode(view.getUint8(offset + i))
  return s
}

async function encodeToView(audio: ClipAudio): Promise<DataView> {
  const blob = encodeWav(audio)
  return new DataView(await blob.arrayBuffer())
}

describe("encodeWav", () => {
  it("writes a 44-byte header plus 2 bytes per mono sample", async () => {
    const blob = encodeWav({ mono: new Float32Array(100), sampleRate: 44100, duration: 100 / 44100 })
    expect(blob.type).toBe("audio/wav")
    expect(blob.size).toBe(44 + 100 * 2)
  })

  it("emits a well-formed 16-bit PCM mono RIFF/WAVE header", async () => {
    const view = await encodeToView({
      mono: new Float32Array(4),
      sampleRate: 48000,
      duration: 4 / 48000,
    })
    expect(ascii(view, 0, 4)).toBe("RIFF")
    expect(ascii(view, 8, 4)).toBe("WAVE")
    expect(ascii(view, 12, 4)).toBe("fmt ")
    expect(ascii(view, 36, 4)).toBe("data")
    expect(view.getUint16(20, true)).toBe(1) // PCM
    expect(view.getUint16(22, true)).toBe(1) // mono
    expect(view.getUint32(24, true)).toBe(48000) // sample rate
    expect(view.getUint16(34, true)).toBe(16) // bits per sample
    expect(view.getUint32(40, true)).toBe(4 * 2) // data byte count
    expect(view.getUint32(4, true)).toBe(36 + 4 * 2) // RIFF chunk size
  })

  it("quantizes samples to signed 16-bit and clamps out-of-range values", async () => {
    const view = await encodeToView({
      mono: new Float32Array([0, 1, -1, 2]), // 2 is out of range → clamps to +full scale
      sampleRate: 8000,
      duration: 4 / 8000,
    })
    expect(view.getInt16(44 + 0 * 2, true)).toBe(0)
    expect(view.getInt16(44 + 1 * 2, true)).toBe(0x7fff) // +1.0
    expect(view.getInt16(44 + 2 * 2, true)).toBe(-0x8000) // -1.0
    expect(view.getInt16(44 + 3 * 2, true)).toBe(0x7fff) // clamped
  })
})
