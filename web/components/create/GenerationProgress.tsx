"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

/**
 * In-flight generation indicator (US-16.7). Shown while the job is polling, with
 * the backend's model-aware time estimate and (when known) the model name, so the
 * estimate visibly reflects the selected model. `progress` carries optional
 * per-step text for long multi-step jobs.
 */
export function GenerationProgress({
  estimatedSeconds,
  modelName,
  progress,
}: {
  estimatedSeconds: number
  modelName?: string
  progress?: string
}) {
  const withModel = modelName ? ` with ${modelName}` : ""
  const estimate = estimatedSeconds > 0 ? ` ~${estimatedSeconds}s` : ""
  return (
    <div
      role="status"
      className="flex flex-col gap-1 text-sm text-muted-foreground"
    >
      <span className="flex items-center gap-2">
        <HugeiconsIcon
          icon={Loading03Icon}
          className="animate-spin"
          data-icon="inline-start"
        />
        Generating{withModel}…{estimate}
      </span>
      {progress && <span className="text-xs">{progress}</span>}
    </div>
  )
}
