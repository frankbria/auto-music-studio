"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { CheckmarkCircle01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { MasteringConfig } from "@/components/mastering/mastering-config"
import { MasteringMetrics } from "@/components/mastering/mastering-metrics"
import { MasteringStatus } from "@/components/mastering/mastering-status"
import { PreviewList } from "@/components/mastering/preview-list"
import { PreviewPlayer } from "@/components/mastering/preview-player"
import { useAuth } from "@/hooks/use-auth"
import { useMasteringJob } from "@/hooks/use-mastering-job"
import { useMasteringPreviews } from "@/hooks/use-mastering-previews"
import { approveMasteringPreview } from "@/lib/mastering"
import type { Clip } from "@/lib/workspace-clips"

/** The approval sub-flow's local state. */
type ApproveState =
  | { phase: "idle" }
  | { phase: "approving" }
  | { phase: "approved"; clipId: string }
  | { phase: "error"; message: string }

/**
 * The mastering tab (US-21.2): the full workflow for one selected song —
 * configure → submit → track progress → audition previews with A/B compare and
 * metrics → approve a master. Composed from small components; the job/preview
 * lifecycle lives in dedicated hooks.
 */
export function MasteringTab({ selectedClip }: { selectedClip: Clip | null }) {
  const { accessToken } = useAuth()
  const job = useMasteringJob()
  const jobId =
    job.state.phase === "completed" ? job.state.detail.job_id : undefined
  const previews = useMasteringPreviews(jobId)
  const [approve, setApprove] = useState<ApproveState>({ phase: "idle" })

  async function handleApprove() {
    if (!jobId || !previews.selectedId) return
    setApprove({ phase: "approving" })
    const result = await approveMasteringPreview(
      jobId,
      previews.selectedId,
      accessToken ?? ""
    )
    if (result.status === "approved") {
      setApprove({ phase: "approved", clipId: result.clipId })
    } else if (result.status === "unauthorized") {
      setApprove({ phase: "error", message: "Please sign in again to approve." })
    } else {
      setApprove({ phase: "error", message: result.detail })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Mastering</CardTitle>
        <CardDescription>
          Choose a profile and service, generate previews, A/B against the
          original, and approve your master.
        </CardDescription>
      </CardHeader>
      <CardContent>{renderBody()}</CardContent>
    </Card>
  )

  function renderBody() {
    // Configure (idle): needs a selected song first.
    if (job.state.phase === "idle") {
      if (!selectedClip) {
        return (
          <p className="text-sm text-muted-foreground">
            Select a song above to start mastering.
          </p>
        )
      }
      return (
        <MasteringConfig
          onStart={(config) => void job.submit(selectedClip.id, config)}
        />
      )
    }

    if (job.state.phase === "submitting") {
      return <MasteringStatus status="submitting" />
    }

    if (job.state.phase === "polling") {
      const status =
        job.state.detail?.status === "processing" ? "processing" : "queued"
      return <MasteringStatus status={status} />
    }

    if (job.state.phase === "error") {
      return (
        <MasteringStatus
          status="failed"
          error={job.state.message}
          onRetry={job.retry}
        />
      )
    }

    // Completed → previews / A-B / approve.
    return renderPreviews()
  }

  function renderPreviews() {
    if (previews.state.status === "loading") {
      return (
        <p role="status" className="text-sm text-muted-foreground">
          Loading previews…
        </p>
      )
    }
    if (previews.state.status === "error") {
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-destructive">Couldn&apos;t load previews.</p>
          <Button variant="outline" size="sm" onClick={previews.reload}>
            Try again
          </Button>
        </div>
      )
    }

    const data = previews.state.data
    const selected = data.previews.find((p) => p.preview_id === previews.selectedId)
    const originalClipId = data.source_clip_id ?? selectedClip?.id

    return (
      <div className="flex flex-col gap-6">
        <PreviewList
          previews={data.previews}
          selectedId={previews.selectedId}
          onSelect={previews.select}
        />

        {selected && originalClipId && (
          <>
            <PreviewPlayer
              originalClipId={originalClipId}
              masteredClipId={selected.preview_id}
            />
            <MasteringMetrics
              metrics={selected.metrics}
              loudnessDelta={selected.loudness_delta}
            />
          </>
        )}

        {approve.phase === "approved" ? (
          <p className="flex items-center gap-2 text-sm text-foreground">
            <HugeiconsIcon
              icon={CheckmarkCircle01Icon}
              size={18}
              className="text-primary"
            />
            Master approved.
            <Badge>Mastered</Badge>
          </p>
        ) : (
          <div className="flex flex-col items-start gap-2">
            <Button
              onClick={handleApprove}
              disabled={!selected || approve.phase === "approving"}
            >
              {approve.phase === "approving" ? "Approving…" : "Approve Master"}
            </Button>
            {approve.phase === "error" && (
              <p className="text-sm text-destructive">{approve.message}</p>
            )}
          </div>
        )}
      </div>
    )
  }
}
