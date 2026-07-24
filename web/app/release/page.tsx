"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MasteringTab } from "@/components/mastering/mastering-tab"
import { DashboardList } from "@/components/distribution/DashboardList"
import { ReviewScreen } from "@/components/distribution/ReviewScreen"
import { DistributionForm } from "@/components/release/DistributionForm"
import { SelectedSongSummary } from "@/components/release/SelectedSongSummary"
import { SongSelector } from "@/components/release/SongSelector"
import { useClip } from "@/hooks/use-clip"
import { useRequireAuth } from "@/hooks/use-require-auth"

// Release page (US-21.1). A single destination for preparing and shipping a
// song: pick a clip (or arrive pre-selected from the Studio's "Send to
// Mastering", which navigates here with ?clip=), see its summary, then work
// through the Mastering and Distribute tabs. Mastering (US-21.2) and the
// distribution metadata form (US-21.4) fill the tab bodies; platform submission
// lands in US-21.5. The Distribute tab splits into Metadata → Review → Releases
// sub-tabs (US-21.6): edit, then verify the package and submit, then track every
// release's per-channel status on the dashboard.
//
// Selection is URL-driven (?clip=): the selector writes it and pre-selection
// reads it, so there's one source of truth and it survives a refresh.

type ReleaseTab = "mastering" | "distribute"

/** Coerce the raw ?tab= value to a known tab (defaults to mastering). */
function parseTab(raw: string | null): ReleaseTab {
  return raw === "distribute" ? "distribute" : "mastering"
}

/** Inner page content (testable without the auth gate / Suspense boundary). */
export function ReleasePageContent() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const tab = parseTab(searchParams.get("tab"))
  const clipId = searchParams.get("clip") ?? undefined
  const { clip, loading, notFound } = useClip(clipId)

  // "Change Song" reopens the selector while keeping the current ?clip= (so a
  // cancel returns to the same song). No clip selected ⇒ selector shows anyway.
  const [picking, setPicking] = useState(false)
  const showSelector = !clipId || picking

  /** Patch a single query param while preserving the rest of the URL. */
  function setParam(key: string, value: string) {
    const params = new URLSearchParams(searchParams.toString())
    params.set(key, value)
    router.replace(`/release?${params.toString()}`)
  }

  function selectClip(id: string) {
    setParam("clip", id)
    setPicking(false)
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Mastering &amp; Distribution</h1>

      {/* Header: song selector or selected-song summary. */}
      {showSelector ? (
        <SongSelector
          onSelect={selectClip}
          onCancel={clipId ? () => setPicking(false) : undefined}
        />
      ) : loading ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading song…
        </p>
      ) : notFound || !clip ? (
        <Card>
          <CardHeader>
            <CardTitle>Song not found</CardTitle>
            <CardDescription>
              That song is unavailable.{" "}
              <button
                type="button"
                className="underline underline-offset-2 hover:text-foreground"
                onClick={() => setPicking(true)}
              >
                Choose another
              </button>
              .
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <SelectedSongSummary clip={clip} onChangeSong={() => setPicking(true)} />
      )}

      <Tabs
        value={tab}
        onValueChange={(next) => setParam("tab", next)}
      >
        <TabsList>
          <TabsTrigger value="mastering">Mastering</TabsTrigger>
          <TabsTrigger value="distribute">Distribute</TabsTrigger>
        </TabsList>
        <TabsContent value="mastering" className="pt-4">
          <MasteringTab selectedClip={clip ?? null} />
        </TabsContent>
        <TabsContent value="distribute" className="pt-4">
          {/* Inner flow (US-21.6): edit metadata → review the package & submit →
              track releases on the dashboard. Local (not URL-driven) sub-tab —
              the outer tab already owns the URL; a second param would be noise. */}
          <Tabs defaultValue="metadata">
            <TabsList>
              <TabsTrigger value="metadata">Metadata</TabsTrigger>
              <TabsTrigger value="review">Review</TabsTrigger>
              <TabsTrigger value="releases">Releases</TabsTrigger>
            </TabsList>

            <TabsContent value="metadata" className="pt-4">
              <Card>
                <CardHeader>
                  <CardTitle>Distribution</CardTitle>
                  <CardDescription>
                    Review and edit your release metadata, then save a draft to
                    continue later. Review and submit from the Review tab.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <DistributionForm clip={clip ?? null} />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="review" className="pt-4">
              <ReviewScreen clip={clip ?? null} />
            </TabsContent>

            <TabsContent value="releases" className="pt-4">
              <Card>
                <CardHeader>
                  <CardTitle>Your releases</CardTitle>
                  <CardDescription>
                    Track every release across channels. Statuses refresh
                    automatically while this tab is open.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <DashboardList />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
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
