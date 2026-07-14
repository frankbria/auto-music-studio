import { vi } from "vitest"

/** Installs fake `requestAnimationFrame`/`cancelAnimationFrame` globals
 * (jsdom has neither) and returns a `tick` to fire every currently-scheduled
 * callback once, at a given time. Shared by every test that drives a rAF
 * loop (playback scheduling, the studio page, and the master bus meter). */
export function stubRaf() {
  let nextId = 1
  const callbacks = new Map<number, FrameRequestCallback>()
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((cb: FrameRequestCallback) => {
      const id = nextId++
      callbacks.set(id, cb)
      return id
    })
  )
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => {
      callbacks.delete(id)
    })
  )
  return {
    /** Invoke every currently-scheduled rAF callback once, at time `t`. */
    tick(t: number) {
      const due = [...callbacks.entries()]
      callbacks.clear()
      for (const [, cb] of due) cb(t)
    },
  }
}
