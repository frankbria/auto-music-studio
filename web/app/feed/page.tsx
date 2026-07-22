import type { Metadata } from "next"

import { FeedView } from "@/components/feed/FeedView"

// Short-form feed (US-20.4): a vertical snap-scroll of auto-playing short clips.
// Web-only for now — items come from the local mock seam (lib/feed) over the same
// discovery pool as Explore, until a `GET /feed` endpoint exists.

export const metadata: Metadata = {
  title: "Feed · Auto Music Studio",
  description: "A vertical feed of short clips that auto-play as you scroll.",
}

export default function FeedPage() {
  return <FeedView />
}
