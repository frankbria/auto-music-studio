import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { PlaylistCover } from "@/components/playlists/PlaylistCover"
import type { Playlist } from "@/lib/playlists"

const pl = (over: Partial<Playlist> = {}): Playlist => ({
  id: "pl-1",
  name: "Mix",
  description: null,
  visibility: "private",
  clipIds: [],
  coverDataUrl: null,
  createdAt: "2026-07-20T00:00:00Z",
  ...over,
})

describe("PlaylistCover", () => {
  it("renders a glyph mosaic by default (AC4)", () => {
    render(<PlaylistCover playlist={pl()} clips={[]} />)
    expect(screen.getByTestId("playlist-mosaic")).toBeInTheDocument()
    expect(screen.queryByRole("img", { name: "Mix cover" })).toBeInTheDocument()
  })

  it("renders the custom cover image when uploaded (AC4)", () => {
    render(<PlaylistCover playlist={pl({ coverDataUrl: "blob:xyz" })} />)
    const img = screen.getByRole("img", { name: "Mix cover" }) as HTMLImageElement
    expect(img.src).toContain("blob:xyz")
    expect(screen.queryByTestId("playlist-mosaic")).not.toBeInTheDocument()
  })
})
