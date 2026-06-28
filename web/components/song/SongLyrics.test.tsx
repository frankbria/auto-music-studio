import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SongLyrics } from "@/components/song/SongLyrics"

describe("SongLyrics", () => {
  it("shows an empty state when there are no lyrics", () => {
    render(<SongLyrics lyrics={null} />)
    expect(screen.getByTestId("lyrics-empty")).toBeInTheDocument()
  })

  it("treats whitespace-only lyrics as empty", () => {
    render(<SongLyrics lyrics={"   \n  "} />)
    expect(screen.getByTestId("lyrics-empty")).toBeInTheDocument()
  })

  it("renders structure tags as labels and the rest as lyric lines", () => {
    render(<SongLyrics lyrics={"[Verse 1]\nHello world\n[Chorus]\nLa la"} />)
    const tags = screen.getAllByTestId("lyrics-tag")
    expect(tags.map((t) => t.textContent)).toEqual(["[Verse 1]", "[Chorus]"])
    expect(screen.getByText("Hello world")).toBeInTheDocument()
    expect(screen.getByText("La la")).toBeInTheDocument()
  })
})
