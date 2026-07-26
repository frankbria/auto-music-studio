import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SourceSongCard } from "@/components/video/SourceSongCard"
import type { Clip } from "@/lib/workspace-clips"

const clip = {
  id: "c1",
  workspace_id: "w1",
  title: "Neon Nights",
  format: "wav",
  duration: 125,
  bpm: 120,
  key: "C",
  style_tags: ["synthwave", "retro"],
  lyrics: null,
  vocal_language: null,
  model: null,
  seed: null,
  inference_steps: null,
  parent_clip_ids: [],
  generation_mode: null,
  is_public: false,
  created_at: "2026-01-01T00:00:00Z",
} as Clip

describe("SourceSongCard", () => {
  it("shows title, duration, and style tags", () => {
    render(<SourceSongCard clip={clip} />)
    expect(screen.getByRole("heading", { name: "Neon Nights" })).toBeInTheDocument()
    expect(screen.getByText("2:05")).toBeInTheDocument()
    expect(screen.getByText("synthwave")).toBeInTheDocument()
    expect(screen.getByText("retro")).toBeInTheDocument()
  })

  it("streams the clip through the cookie-authed proxy and toggles play", () => {
    render(<SourceSongCard clip={clip} />)
    const audio = screen.getByTestId("source-audio") as HTMLAudioElement
    expect(audio).toHaveAttribute("src", "/api/clips/c1/stream")

    fireEvent.click(screen.getByRole("button", { name: /play/i }))
    // jsdom's play() is a stub that doesn't fire events; simulate the browser.
    fireEvent.play(audio)
    expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument()
    fireEvent.pause(audio)
    expect(screen.getByRole("button", { name: /play/i })).toBeInTheDocument()
  })
})
