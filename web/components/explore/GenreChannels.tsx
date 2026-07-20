import Link from "next/link"

import { getGenreChannels } from "@/lib/explore"
import { SectionRow } from "./SectionRow"

// Genre channel tiles (US-20.1, AC3). Each tile links to the genre-filtered
// search view. Styled distinctly from clip cards — larger, bold label on a
// per-genre gradient — so channels read as navigation, not individual songs.

// Deterministic gradient per genre so tiles look varied but stable across
// renders (no artwork to key off of yet).
const GRADIENTS = [
  "from-rose-500/70 to-orange-400/70",
  "from-sky-500/70 to-indigo-500/70",
  "from-amber-500/70 to-yellow-400/70",
  "from-violet-500/70 to-fuchsia-500/70",
  "from-emerald-500/70 to-teal-400/70",
  "from-pink-500/70 to-purple-500/70",
  "from-cyan-500/70 to-blue-500/70",
  "from-lime-500/70 to-green-500/70",
]

export function GenreChannels() {
  const genres = getGenreChannels()
  return (
    <SectionRow title="Genre Channels">
      {genres.map((genre, i) => (
        <Link
          key={genre.id}
          href={`/search?style=${genre.slug}`}
          data-testid="genre-tile"
          className={`flex aspect-video w-48 shrink-0 items-end rounded-lg bg-gradient-to-br p-3 text-lg font-bold text-white shadow-sm outline-none transition-transform hover:scale-[1.02] focus-visible:ring-3 focus-visible:ring-ring/50 ${GRADIENTS[i % GRADIENTS.length]}`}
        >
          {genre.name}
        </Link>
      ))}
    </SectionRow>
  )
}
