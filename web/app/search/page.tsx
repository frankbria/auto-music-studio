import { Suspense } from "react"
import type { Metadata } from "next"

import { SearchPageClient } from "@/components/search/SearchPageClient"

// Search page (US-20.2): full-text search over the discovery pool with genre/
// BPM/key/model filters and relevance/newest/popular sort, all reflected in the
// URL for shareable links. Data comes from the local mock seam (lib/search)
// until a public discovery search endpoint exists — the `GET /clips` list is
// auth-gated and owner-scoped, so it can't back an anonymous listener search.
//
// useSearchParams() requires a Suspense boundary in the App Router, so the URL
// bridge renders inside one.

export const metadata: Metadata = {
  title: "Search · Auto Music Studio",
  description: "Search songs by text, genre, BPM, key, and model.",
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchPageClient />
    </Suspense>
  )
}
