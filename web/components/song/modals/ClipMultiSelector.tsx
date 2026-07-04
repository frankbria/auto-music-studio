"use client"

import { useClips } from "@/hooks/use-clips"
import { MASHUP_CLIPS_MAX, MASHUP_CLIPS_MIN } from "@/lib/constants/editing"

// Multi-clip picker for the Mashup modal (US-17.3). Lists the workspace's clips
// and lets the user pick which ones to combine, keeping selection *order* (the
// first pick is the mashup's primary). The backend mashup needs WAV sources that
// carry duration metadata, so ineligible clips are filtered out entirely rather
// than shown-but-disabled. Selection is capped at MASHUP_CLIPS_MAX: once the cap
// is reached the remaining checkboxes go disabled instead of silently no-oping.

export function ClipMultiSelector({
  workspaceId,
  selected,
  onChange,
}: {
  workspaceId: string
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const { data, loading } = useClips(
    { workspace_id: workspaceId, per_page: 50 },
    { enabled: true }
  )

  const eligible = (data?.clips ?? []).filter(
    (clip) => clip.format === "wav" && clip.duration != null
  )

  function toggle(id: string) {
    if (selected.includes(id)) {
      onChange(selected.filter((s) => s !== id))
    } else {
      onChange([...selected, id])
    }
  }

  const atMax = selected.length >= MASHUP_CLIPS_MAX

  return (
    <div className="flex flex-col gap-2">
      {loading ? (
        <p className="py-4 text-sm text-muted-foreground">Loading clips…</p>
      ) : eligible.length === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">
          No eligible clips to mash up.
        </p>
      ) : (
        <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
          {eligible.map((clip) => {
            const checked = selected.includes(clip.id)
            return (
              <li key={clip.id}>
                <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!checked && atMax}
                    onChange={() => toggle(clip.id)}
                    className="size-4 shrink-0"
                  />
                  <span className="truncate">{clip.title || "Untitled"}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                    {clip.duration}s
                    {clip.bpm != null && ` · ${clip.bpm} BPM`}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      )}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{selected.length} selected</span>
        {selected.length < MASHUP_CLIPS_MIN && (
          <span>Select at least {MASHUP_CLIPS_MIN} clips.</span>
        )}
      </div>
    </div>
  )
}
