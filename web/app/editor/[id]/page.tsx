"use client"

import { useParams } from "next/navigation"

import { ClipEditor } from "@/components/editor/ClipEditor"

// Waveform-editor route /editor/[id] (US-18.1, first story of Stage 18). Thin
// shim: pull the id from the route and hand off to ClipEditor, which owns auth,
// data fetching, audio decoding, and layout. Reached from the song menu's
// "Open in Editor" action (song-actions → navigation).

export default function EditorPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id
  if (!id) return null
  return <ClipEditor clipId={id} />
}
