"use client"

import { useParams } from "next/navigation"

import { SongDetail } from "@/components/song/SongDetail"

// Song detail route /song/[id] (US-17.1). Thin shim: pull the id from the route
// and hand off to SongDetail, which owns auth, data fetching, and layout.

export default function SongPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id
  if (!id) return null
  return <SongDetail clipId={id} />
}
