import { vi } from "vitest"

// Fake Web Audio node stand-ins (jsdom has none of these) shared by every
// test that exercises the master bus chain (US-19.5): the playback hook's
// own AudioContext stub, the studio page's, and the panel/meter component
// tests that construct nodes directly without a full AudioContext.

export class FakeBiquadFilterNode {
  type: BiquadFilterType = "lowpass"
  connect = vi.fn()
  disconnect = vi.fn()
  frequency = { value: 350 }
  gain = { value: 0 }
  Q = { value: 1 }
}

export class FakeDynamicsCompressorNode {
  connect = vi.fn()
  disconnect = vi.fn()
  threshold = { value: -24 }
  knee = { value: 30 }
  ratio = { value: 12 }
  attack = { value: 0.003 }
  release = { value: 0.25 }
  reduction = 0
}

export class FakeChannelSplitterNode {
  connect = vi.fn()
  disconnect = vi.fn()
}

export class FakeAnalyserNode {
  connect = vi.fn()
  disconnect = vi.fn()
  fftSize = 2048
  getFloatTimeDomainData = vi.fn()
}
