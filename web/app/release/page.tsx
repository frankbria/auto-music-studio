"use client"

import { Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useClip } from "@/hooks/use-clip"
import { useRequireAuth } from "@/hooks/use-require-auth"
import { formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

// Minimal release landing (US-19.6). The studio's "Send to Mastering" bounces a
// mix and lands here with the new clip pre-selected via ?clip=. This page only
// confirms the hand-off (selected-song summary) and stubs Distribute — the full
// mastering workflow is Stage 21 (US-21.1+), which owns this page's real body.

type ReleaseTab = "mastering" | "distribute"

/** Coerce the raw ?tab= value to a known tab (defaults to mastering). */
function parseTab(raw: string | null): ReleaseTab {
  return raw === "distribute" ? "distribute" : "mastering"
}

/** The pre-selected song's summary, or an empty state prompting a hand-off. */
function MasteringTab({
  clipId,
  clip,
  loading,
  notFound,
}: {
  clipId: string | undefined
  clip: Clip | null
  loading: boolean
  notFound: boolean
}) {
  if (!clipId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No song selected</CardTitle>
          <CardDescription>
            Send a mix from the Studio&apos;s master bus to master it here.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }
  if (loading) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading song…
      </p>
    )
  }
  if (notFound || !clip) {
    return <p className="text-sm text-muted-foreground">Song not found.</p>
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>{clip.title ?? "Untitled"}</CardTitle>
        <CardDescription>{formatTime(clip.duration ?? 0)}</CardDescription>
      </CardHeader>
      <CardContent>
        <Badge>Ready for mastering</Badge>
      </CardContent>
    </Card>
  )
}

function DistributeTab() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribution</CardTitle>
        <CardDescription>
          Publishing to streaming platforms is coming soon.
        </CardDescription>
      </CardHeader>
    </Card>
  )
}

/** Inner page content (testable without the auth gate / Suspense boundary). */
export function ReleasePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const tab = parseTab(searchParams.get("tab"))
  const clipId = searchParams.get("clip") ?? undefined
  const { clip, loading, notFound } = useClip(clipId)

  return (
    <div className="flex flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Mastering &amp; Distribution</h1>
      <Tabs
        value={tab}
        onValueChange={(next) => {
          // Preserve the rest of the query (notably ?clip= from Send to
          // Mastering) — replacing with only ?tab= would drop the hand-off.
          const params = new URLSearchParams(searchParams.toString())
          params.set("tab", next)
          router.replace(`/release?${params.toString()}`)
        }}
      >
        <TabsList>
          <TabsTrigger value="mastering">Mastering</TabsTrigger>
          <TabsTrigger value="distribute">Distribute</TabsTrigger>
        </TabsList>
        <TabsContent value="mastering" className="pt-4">
          <MasteringTab
            clipId={clipId}
            clip={clip}
            loading={loading}
            notFound={notFound}
          />
        </TabsContent>
        <TabsContent value="distribute" className="pt-4">
          <DistributeTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function ReleaseGate() {
  const { isLoading, isAuthenticated } = useRequireAuth()
  // Render nothing until authed — useRequireAuth redirects otherwise (mirrors
  // app/studio/page.tsx).
  if (isLoading || !isAuthenticated) return null
  return <ReleasePageContent />
}

export default function ReleasePage() {
  // useSearchParams requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <ReleaseGate />
    </Suspense>
  )
}
