"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { SearchView } from "@/components/search/SearchView"
import {
  buildSearchQuery,
  parseSearchParams,
  type SearchParams,
} from "@/lib/search"

// URL bridge for the Search page (US-20.2). The URL is the single source of
// truth: search state is derived from useSearchParams() on every render, so a
// shared link, a genre deep link, or browser back/forward into /search?… is
// reflected immediately — no set-state-in-effect sync and no URL↔state loop.
// The only transient local state is SearchView's debounced search box.

export function SearchPageClient() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const params = parseSearchParams(
    new URLSearchParams(searchParams?.toString() ?? "")
  )

  const update = (patch: Partial<SearchParams>) => {
    const next = { ...params, ...patch }
    // Any change other than paging returns to the first page.
    if (!("page" in patch)) next.page = 1
    const query = buildSearchQuery(next)
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  return <SearchView params={params} onChange={update} />
}
