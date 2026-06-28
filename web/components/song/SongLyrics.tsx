"use client"

// Song-detail lyrics panel (US-17.1). Renders lyrics line by line; structure
// tags on their own line (e.g. "[Verse 1]", "[Chorus]") are styled as section
// labels, everything else as lyric text. Scrolls when long.
//
// ponytail: line-based parse is enough — ACE-Step lyrics use bracketed tags on
// their own lines. No need for a full lyric grammar.

const TAG_LINE = /^\s*\[.+\]\s*$/

export function SongLyrics({ lyrics }: { lyrics: string | null }) {
  const text = lyrics?.trim()
  if (!text) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="lyrics-empty">
        No lyrics for this song.
      </p>
    )
  }

  const lines = text.split("\n")
  return (
    <div className="max-h-96 overflow-y-auto" data-testid="lyrics">
      {lines.map((line, i) =>
        TAG_LINE.test(line) ? (
          <p
            key={i}
            data-testid="lyrics-tag"
            className="mt-3 text-xs font-semibold tracking-wide text-primary uppercase first:mt-0"
          >
            {line.trim()}
          </p>
        ) : line.trim() === "" ? (
          <div key={i} className="h-2" aria-hidden />
        ) : (
          <p key={i} className="text-sm whitespace-pre-wrap">
            {line}
          </p>
        )
      )}
    </div>
  )
}
