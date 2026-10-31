import type { Metadata } from "next"

import { FeedView } from "@/components/feed/FeedView"

// Short-form feed (US-20.4): a vertical snap-scroll of auto-playing public clips,
// newest first, from the public discovery API (#651) via lib/feed.

export const metadata: Metadata = {
  title: "Feed · Auto Music Studio",
  description: "A vertical feed of short clips that auto-play as you scroll.",
}

export default function FeedPage() {
  return <FeedView />
}
