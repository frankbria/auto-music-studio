import type { Metadata } from "next"

import { DiscoverSection } from "@/components/explore/DiscoverSection"
import { GenreChannels } from "@/components/explore/GenreChannels"
import { NewReleasesSection } from "@/components/explore/NewReleasesSection"
import { TrendingSection } from "@/components/explore/TrendingSection"

// Explore page (US-20.1): Genre Channels that deep-link into Search, and rows from the public discovery API (#651),
// fetched client-side through the BFF. Trending, Staff Picks and Charts rank by recorded plays, likes, shares and
// admin picks (#656).

export const metadata: Metadata = {
  title: "Explore · Auto Music Studio",
  description:
    "Browse trending songs, staff picks, charts, genre channels and new releases.",
}

export default function ExplorePage() {
  return (
    <div className="flex flex-col gap-10 p-8">
      <h1 className="text-2xl font-semibold">Explore</h1>
      <TrendingSection />
      <GenreChannels />
      <DiscoverSection
        title="Staff Picks"
        sort="staff_picks"
        emptyText="No staff picks yet."
      />
      <NewReleasesSection />
      <DiscoverSection
        title="Charts"
        sort="popular"
        ranked
        emptyText="No plays yet."
      />
    </div>
  )
}
