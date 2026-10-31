import { Suspense } from "react"
import type { Metadata } from "next"

import { SearchPageClient } from "@/components/search/SearchPageClient"

// Search page (US-20.2): full-text search over public clips with genre/BPM/key/
// model filters and relevance/newest sort, all reflected in the URL for shareable
// links. Results come from the public discovery API (#651) via lib/search.
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
