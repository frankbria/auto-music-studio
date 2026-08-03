"use client"

import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useVoiceModels } from "@/hooks/use-voice-models"
import { useVoiceTraining } from "@/hooks/use-voice-training"
import { describePhase, type VoiceModelSummary } from "@/lib/voice-models"

/** Status wording the musician sees, rather than the raw enum. */
const STATUS_LABEL: Record<VoiceModelSummary["status"], string> = {
  queued: "Queued",
  training: "Training",
  ready: "Ready",
  failed: "Failed",
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString()
}

/** Live progress for a model still training (US-25.2's hook, reused here). */
function TrainingProgress({ jobId }: { jobId: string }) {
  const { state } = useVoiceTraining(jobId)

  if (state.phase === "error") {
    return <p className="text-sm text-destructive">{state.message}</p>
  }

  if (state.phase !== "polling" && state.phase !== "settled") {
    return <p className="text-sm text-muted-foreground">Checking progress…</p>
  }

  const { status } = state

  return (
    <p className="text-sm text-muted-foreground">
      {describePhase(status)}
      {/* null progress means the server cannot know it -- showing 0% would read
          as "stuck", so the phase stands alone instead. */}
      {status.progress !== null ? ` — ${Math.round(status.progress)}%` : ""}
    </p>
  )
}

function VoiceCard({
  model,
  onRename,
  onDelete,
}: {
  model: VoiceModelSummary
  onRename: (id: string, name: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(model.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await onRename(model.id, draft)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not rename.")
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await onDelete(model.id)
    } catch (e) {
      // A model still training refuses deletion (409) -- show why rather than
      // failing silently.
      setError(e instanceof Error ? e.message : "Could not delete.")
      setBusy(false)
    }
  }

  return (
    <li className="rounded-lg border border-border p-4" data-testid="voice-card">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {editing ? (
            <div className="flex items-center gap-2">
              <Input
                aria-label="Voice name"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                className="h-8 w-48"
              />
              <Button size="sm" onClick={save} disabled={busy}>
                Save
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDraft(model.name)
                  setEditing(false)
                  setError(null)
                }}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <h3 className="truncate font-medium">{model.name}</h3>
          )}

          {model.description ? (
            <p className="mt-1 truncate text-sm text-muted-foreground">{model.description}</p>
          ) : null}

          <p className="mt-2 text-xs text-muted-foreground">
            {model.reference_count} reference
            {model.reference_count === 1 ? "" : "s"}
            {formatDate(model.created_at) ? ` · ${formatDate(model.created_at)}` : ""}
          </p>

          {model.status === "training" || model.status === "queued" ? (
            model.job_id ? (
              <div className="mt-2">
                <TrainingProgress jobId={model.job_id} />
              </div>
            ) : null
          ) : null}

          {model.status === "failed" && model.error ? (
            <p className="mt-2 text-sm text-destructive">{model.error}</p>
          ) : null}

          {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Badge variant={model.status === "ready" ? "default" : "secondary"}>
            {STATUS_LABEL[model.status]}
          </Badge>
          {!editing ? (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)} disabled={busy}>
              Rename
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={remove} disabled={busy}>
            Delete
          </Button>
        </div>
      </div>
    </li>
  )
}

/**
 * The musician's voice model library (US-25.3).
 *
 * Lists every trained voice with its name, description, creation date, reference
 * count and training status, and supports renaming and deleting. A model still
 * training shows live progress rather than a dead card.
 *
 * **No preview.** Generating with a voice means loading its LoRA, and that is
 * server-global state in ACE-Step (`dit_handler.use_lora`, no per-request field),
 * so previewing one musician's voice would change the model for everyone else on
 * that server — and unloading is unreliable. See the note on #327.
 */
export function VoiceLibrary() {
  const { state, rename, remove } = useVoiceModels()

  if (state.phase === "loading") {
    return <p className="text-sm text-muted-foreground">Loading your voices…</p>
  }

  if (state.phase === "signed-out") {
    return <p className="text-sm text-muted-foreground">Sign in to see your voices.</p>
  }

  if (state.phase === "error") {
    return <p className="text-sm text-destructive">{state.message}</p>
  }

  if (state.models.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No voice models yet. Train one from a few reference recordings to use your own voice
        in a generation.
      </p>
    )
  }

  return (
    <ul className="space-y-3">
      {state.models.map((model) => (
        <VoiceCard
          key={model.id}
          model={model}
          onRename={(id, name) => rename(id, { name })}
          onDelete={remove}
        />
      ))}
    </ul>
  )
}
