import type { Metadata } from "next"

import { GenreChannels } from "@/components/explore/GenreChannels"
import { NewReleasesSection } from "@/components/explore/NewReleasesSection"

// Explore page (US-20.1): static Genre Channels that deep-link into Search, and
// New Releases from the public discovery API (#651), fetched client-side
// through the BFF. Trending, Staff Picks and Charts are hidden until the
// backend records the plays/likes/shares or editorial picks they rank by.

export const metadata: Metadata = {
  title: "Explore · Auto Music Studio",
  description: "Browse genre channels and the newest public songs.",
}

export default function ExplorePage() {
  return (
    <div className="flex flex-col gap-10 p-8">
      <h1 className="text-2xl font-semibold">Explore</h1>
      <GenreChannels />
      <NewReleasesSection />
    </div>
  )
}
