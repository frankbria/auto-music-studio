"use client"

import { Suspense, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MasteringTab } from "@/components/mastering/mastering-tab"
import { SelectedSongSummary } from "@/components/release/SelectedSongSummary"
import { SongSelector } from "@/components/release/SongSelector"
import { useClip } from "@/hooks/use-clip"
import { useRequireAuth } from "@/hooks/use-require-auth"

// Release page (US-21.1). A single destination for preparing and shipping a
// song: pick a clip (or arrive pre-selected from the Studio's "Send to
// Mastering", which navigates here with ?clip=), see its summary, then work
// through the Mastering and Distribute tabs. The tab body placeholders are
// filled by US-21.2 (mastering) and US-21.4/21.5 (distribution).
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
          <Card>
            <CardHeader>
              <CardTitle>Distribution</CardTitle>
              <CardDescription>
                Publishing to streaming platforms is coming soon.
              </CardDescription>
            </CardHeader>
          </Card>
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
