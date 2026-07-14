"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  FileExportIcon,
  FolderExportIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useStudio } from "@/contexts/studio-context"
import { useAuth } from "@/hooks/use-auth"
import { useStudioExport } from "@/hooks/use-studio-export"
import { useWorkspaces } from "@/hooks/use-workspaces"
import {
  buildDawExportRequest,
  buildMixdownRequest,
  type StudioFormat,
} from "@/lib/studio-export"

// Studio export menu (US-19.6): "Export Mixdown" (WAV/FLAC/MP3) bounces the
// arrangement to a single "Studio"-badged clip in the workspace; "Export for
// DAW" produces a stems-plus-metadata ZIP. Each choice builds the full request
// from the current StudioState and hands it to useStudioExport, which submits,
// polls, and (for DAW) downloads the bundle. Progress surfaces inline via a
// role="status" region — the app has no toast layer.

// The studio has no project-name field yet; a stable default names the mixdown
// clip and the DAW bundle's ZIP.
const DEFAULT_PROJECT_NAME = "Studio Mix"

const FORMATS: { format: StudioFormat; label: string }[] = [
  { format: "wav", label: "WAV" },
  { format: "flac", label: "FLAC" },
  { format: "mp3", label: "MP3" },
]

export function ExportMenu({
  onMixdownComplete,
}: {
  /** Bumped by the studio page on a completed mixdown so the new clip appears. */
  onMixdownComplete?: () => void
}) {
  const { state } = useStudio()
  const { accessToken } = useAuth()
  const { defaultWorkspace } = useWorkspaces()
  const { state: exportState, exportMixdown, exportDaw } = useStudioExport({
    onMixdownComplete: () => onMixdownComplete?.(),
  })

  const workspaceId = defaultWorkspace?.id
  const hasContent = state.tracks.some((t) => t.clips.length > 0)
  const busy =
    exportState.phase === "submitting" || exportState.phase === "polling"
  // Can't export without a resolved workspace, a token, or any placed clips.
  const disabled = !workspaceId || !accessToken || !hasContent || busy

  const opts = {
    workspaceId: workspaceId ?? "",
    projectName: DEFAULT_PROJECT_NAME,
  }

  function runMixdown(format: StudioFormat) {
    if (!accessToken || !workspaceId) return
    void exportMixdown(buildMixdownRequest(state, { ...opts, format }), accessToken)
  }

  function runDaw() {
    if (!accessToken || !workspaceId) return
    void exportDaw(buildDawExportRequest(state, opts), accessToken)
  }

  return (
    <div className="flex items-center gap-2">
      <ExportStatus state={exportState} />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            aria-label="Export"
          >
            <HugeiconsIcon icon={FileExportIcon} data-icon="inline-start" />
            Export
            <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel>Export Mixdown</DropdownMenuLabel>
          <DropdownMenuGroup>
            {FORMATS.map(({ format, label }) => (
              <DropdownMenuItem
                key={format}
                onSelect={() => runMixdown(format)}
              >
                <HugeiconsIcon icon={FileExportIcon} data-icon="inline-start" />
                {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={runDaw}>
            <HugeiconsIcon icon={FolderExportIcon} data-icon="inline-start" />
            Export for DAW
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** Inline progress / error readout — the app has no toast layer (US-19.6). */
function ExportStatus({
  state,
}: {
  state: ReturnType<typeof useStudioExport>["state"]
}) {
  let text: string | null = null
  if (state.phase === "submitting") text = "Queued…"
  else if (state.phase === "polling") text = state.progress ?? "Queued…"
  else if (state.phase === "success") text = "Export complete"
  else if (state.phase === "error") text = state.message

  if (!text) return null
  return (
    <span
      role="status"
      className="text-xs text-muted-foreground"
      data-phase={state.phase}
    >
      {text}
    </span>
  )
}
