import type { Clip } from "@/lib/workspace-clips"

/** A valid WAV clip with duration + BPM; override only what a test exercises. */
export function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip-1",
    workspace_id: "ws-1",
    title: "Midnight Drive",
    format: "wav",
    duration: 60,
    bpm: 120,
    key: "C minor",
    style_tags: ["lofi"],
    lyrics: null,
    vocal_language: null,
    model: "ace-step-v1",
    seed: 7,
    inference_steps: 30,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}
