"use client"

import { notFound, useParams } from "next/navigation"

import { ProfileView } from "@/components/profile/ProfileView"

// Public profile route /@handle (US-20.5). This is a root dynamic segment, so it
// also catches unknown top-level paths — static routes (/explore, /search, …) win
// over it, and anything reaching here that isn't "@handle" is a 404. The "@" is
// part of the captured param; ProfileView strips it and 404s on an unknown handle.

export default function ProfilePage() {
  const params = useParams<{ handle: string }>()
  const handle = decodeHandle(params?.handle)
  if (!handle.startsWith("@")) notFound()
  // key={handle} forces a fresh mount per profile: the App Router reuses this
  // component instance across /@a → /@b navigations, which would otherwise carry
  // ProfileView's optimistic follow state onto the next profile.
  return <ProfileView key={handle} handle={handle} />
}

/**
 * Decode the raw route segment (useParams returns it still percent-encoded).
 * A malformed escape (a lone "%", "/%zz") would throw URIError; a root catch-all
 * sees arbitrary bot/crawler paths, so degrade those to a 404 like any bad handle.
 */
function decodeHandle(raw: string | undefined): string {
  if (!raw) return ""
  try {
    return decodeURIComponent(raw)
  } catch {
    return ""
  }
}
