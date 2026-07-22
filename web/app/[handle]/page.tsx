"use client"

import { notFound, useParams } from "next/navigation"

import { ProfileView } from "@/components/profile/ProfileView"

// Public profile route /@handle (US-20.5). This is a root dynamic segment, so it
// also catches unknown top-level paths — static routes (/explore, /search, …) win
// over it, and anything reaching here that isn't "@handle" is a 404. The "@" is
// part of the captured param; ProfileView strips it and 404s on an unknown handle.

export default function ProfilePage() {
  const params = useParams<{ handle: string }>()
  const handle = params?.handle ? decodeURIComponent(params.handle) : ""
  if (!handle.startsWith("@")) notFound()
  return <ProfileView handle={handle} />
}
