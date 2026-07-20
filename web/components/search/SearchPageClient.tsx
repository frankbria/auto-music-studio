"use client"

import { useEffect, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { SearchView } from "@/components/search/SearchView"
import {
  buildSearchQuery,
  parseSearchParams,
  type SearchParams,
} from "@/lib/search"

// URL bridge for the Search page (US-20.2). Reads the initial search state from
// the URL once on mount, then owns it locally and mirrors every change back to
// the URL via router.replace (shareable links — AC4). Sync is one-directional
// (state → URL), which keeps it loop-free and off the set-state-in-effect lint;
// the trade-off is that browser back/forward doesn't re-drive in-page state.

export function SearchPageClient() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const [params, setParams] = useState<SearchParams>(() =>
    parseSearchParams(new URLSearchParams(searchParams?.toString() ?? ""))
  )

  // Mirror state to the URL. Not set-state-in-effect — it syncs an external
  // system (the router), which is the sanctioned use of an effect.
  useEffect(() => {
    const query = buildSearchQuery(params)
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }, [params, pathname, router])

  const update = (patch: Partial<SearchParams>) =>
    setParams((prev) => {
      const next = { ...prev, ...patch }
      // Any change other than paging returns to the first page.
      if (!("page" in patch)) next.page = 1
      return next
    })

  return <SearchView params={params} onChange={update} />
}
