import type { ClipAudio } from "@/lib/audio-peaks"

// Encode the editor's decoded audio back to a real file (US-18.4). The editor
// holds audio as a mono Float32Array (see ClipAudio); "Save as new version"
// needs bytes to upload, so this serializes it as a 16-bit PCM mono WAV — the
// simplest lossless container every backend/decoder understands. No external
// dependency: a WAV is a 44-byte header followed by the samples.

const BYTES_PER_SAMPLE = 2 // 16-bit PCM

/** Clamp to [-1, 1] and quantize to the nearest signed 16-bit integer. */
function toInt16(sample: number): number {
  const s = Math.max(-1, Math.min(1, sample))
  // Round (not truncate — setInt16 would truncate toward zero, biasing every
  // sample down by up to ~1 LSB). Asymmetric range: floor -32768, ceiling +32767.
  return s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff)
}

/** Serialize mono `ClipAudio` as a 16-bit PCM WAV `Blob`. */
export function encodeWav(audio: ClipAudio): Blob {
  const { mono, sampleRate } = audio
  const dataBytes = mono.length * BYTES_PER_SAMPLE
  const buffer = new ArrayBuffer(44 + dataBytes)
  const view = new DataView(buffer)

  const writeAscii = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
  }

  // RIFF header
  writeAscii(0, "RIFF")
  view.setUint32(4, 36 + dataBytes, true) // file size minus the first 8 bytes
  writeAscii(8, "WAVE")
  // fmt chunk
  writeAscii(12, "fmt ")
  view.setUint32(16, 16, true) // PCM fmt chunk size
  view.setUint16(20, 1, true) // audio format 1 = PCM
  view.setUint16(22, 1, true) // channels = mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true) // byte rate
  view.setUint16(32, BYTES_PER_SAMPLE, true) // block align
  view.setUint16(34, 8 * BYTES_PER_SAMPLE, true) // bits per sample
  // data chunk
  writeAscii(36, "data")
  view.setUint32(40, dataBytes, true)
  for (let i = 0; i < mono.length; i++) {
    view.setInt16(44 + i * BYTES_PER_SAMPLE, toInt16(mono[i]), true)
  }

  return new Blob([buffer], { type: "audio/wav" })
}
