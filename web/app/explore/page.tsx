import type { Metadata } from "next"

import { ClipSection } from "@/components/explore/ClipSection"
import { GenreChannels } from "@/components/explore/GenreChannels"
import { TrendingSection } from "@/components/explore/TrendingSection"
import { getCharts, getNewReleases, getStaffPicks } from "@/lib/explore"

// Explore page (US-20.1): five discovery sections — Trending (24h/7d),
// Genre Channels, Staff Picks, New Releases, and Charts. Data comes from the
// local mock service (lib/explore) until public discovery endpoints exist; the
// page stays a server component and only Trending opts into the client for its
// range toggle.

export const metadata: Metadata = {
  title: "Explore · Auto Music Studio",
  description:
    "Discover trending songs, genre channels, staff picks, new releases, and charts.",
}

export default function ExplorePage() {
  return (
    <div className="flex flex-col gap-10 p-8">
      <h1 className="text-2xl font-semibold">Explore</h1>
      <TrendingSection />
      <GenreChannels />
      <ClipSection title="Staff Picks" clips={getStaffPicks()} />
      <ClipSection title="New Releases" clips={getNewReleases()} />
      <ClipSection title="Charts" clips={getCharts("plays")} ranked />
    </div>
  )
}
