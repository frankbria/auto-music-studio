"use client"

import { useEffect, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  RecordIcon,
  StopIcon,
  Upload04Icon,
} from "@hugeicons/core-free-icons"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useClips } from "@/hooks/use-clips"
import { useWorkspaces } from "@/hooks/use-workspaces"
import { SELECT_CLASS } from "@/lib/constants/ui"
import {
  ACCEPTED_AUDIO_EXTENSIONS,
  isAcceptedAudioFile,
  type AudioSelection,
} from "@/lib/audio-inputs"
import { AudioPreview } from "@/components/create/AudioPreview"

// Sentinel workspace id for the "Public Songs" option — queries clips without a
// workspace scope. ponytail: simplest mapping until a dedicated public feed lands.
const PUBLIC = "__public__"

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—"
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

/**
 * Add Audio modal (US-16.8): attach a reference audio via one of three tabs —
 * Remix (pick an existing clip), Upload (a local file), or Record (the mic).
 * Controlled via `open`/`onOpenChange`; `onSelect` receives the chosen
 * AudioSelection and the caller closes the modal.
 */
export function AddAudioModal({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (selection: AudioSelection) => void
}) {
  function choose(selection: AudioSelection) {
    onSelect(selection)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add audio</DialogTitle>
          <DialogDescription>
            Remix an existing clip, upload a file, or record from your
            microphone.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="remix">
          <TabsList>
            <TabsTrigger value="remix">Remix</TabsTrigger>
            <TabsTrigger value="upload">Upload</TabsTrigger>
            <TabsTrigger value="record">Record</TabsTrigger>
          </TabsList>

          <TabsContent value="remix">
            <RemixTab onSelect={choose} active={open} />
          </TabsContent>
          <TabsContent value="upload">
            <UploadTab onSelect={choose} />
          </TabsContent>
          <TabsContent value="record">
            <RecordTab onSelect={choose} active={open} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function RemixTab({
  onSelect,
  active,
}: {
  onSelect: (selection: AudioSelection) => void
  active: boolean
}) {
  const { workspaces, defaultWorkspace } = useWorkspaces()
  // `selected` is null until the user picks; the effective workspace falls back
  // to their default. Deriving (rather than syncing via an effect) keeps this
  // clear of the react-hooks/set-state-in-effect rule.
  const [selected, setSelected] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  const workspaceId = selected ?? defaultWorkspace?.id ?? ""
  const isPublic = workspaceId === PUBLIC
  const { data, loading } = useClips(
    {
      workspace_id: isPublic ? undefined : workspaceId || undefined,
      search: search || undefined,
    },
    { enabled: active && (isPublic || !!workspaceId) }
  )
  const clips = data?.clips ?? []

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Workspace"
          className={`${SELECT_CLASS} w-auto`}
          value={workspaceId}
          onChange={(e) => setSelected(e.target.value)}
        >
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
          <option value={PUBLIC}>Public Songs</option>
        </select>
        <Input
          aria-label="Search clips"
          placeholder="Search by title or style..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1"
        />
      </div>

      <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
        {loading && (
          <li className="px-2 py-3 text-sm text-muted-foreground">Loading…</li>
        )}
        {!loading && clips.length === 0 && (
          <li className="px-2 py-3 text-sm text-muted-foreground">
            No clips found.
          </li>
        )}
        {clips.map((clip) => {
          const title = clip.title || "Untitled clip"
          return (
            <li key={clip.id}>
              <button
                type="button"
                onClick={() =>
                  onSelect({ kind: "clip", clipId: clip.id, label: title })
                }
                className="flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-sm hover:bg-muted"
              >
                <span className="truncate">{title}</span>
                <span className="ml-2 shrink-0 text-xs text-muted-foreground">
                  {formatDuration(clip.duration)}
                  {clip.bpm ? ` · ${clip.bpm} BPM` : ""}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function UploadTab({
  onSelect,
}: {
  onSelect: (selection: AudioSelection) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  function accept(candidate: File | undefined) {
    if (!candidate) return
    if (!isAcceptedAudioFile(candidate.name)) {
      setFile(null)
      setError(
        `Unsupported file type. Use ${ACCEPTED_AUDIO_EXTENSIONS.join(", ")}.`
      )
      return
    }
    setError(null)
    setFile(candidate)
  }

  if (file) {
    return (
      <div className="flex flex-col gap-3">
        <AudioPreview
          source={file}
          label={file.name}
          onClear={() => setFile(null)}
        />
        <Button
          type="button"
          className="w-fit"
          onClick={() =>
            onSelect({ kind: "upload", file, label: file.name })
          }
        >
          Attach
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          accept(e.dataTransfer.files[0])
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground ${
          dragging ? "border-primary bg-primary/5" : "border-border"
        }`}
      >
        <HugeiconsIcon icon={Upload04Icon} size={24} />
        <p>Drag and drop an audio file here</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
        >
          Browse files
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_AUDIO_EXTENSIONS.join(",")}
          aria-label="Upload audio file"
          className="hidden"
          onChange={(e) => accept(e.target.files?.[0])}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

function RecordTab({
  onSelect,
  active,
}: {
  onSelect: (selection: AudioSelection) => void
  active: boolean
}) {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [denied, setDenied] = useState(false)

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  // Stop any in-flight recording / timer when the modal closes or unmounts.
  useEffect(() => {
    if (!active) {
      if (recorderRef.current?.state === "recording") recorderRef.current.stop()
      stopTimer()
    }
    return stopTimer
  }, [active])

  async function start() {
    setDenied(false)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = () => {
        setBlob(new Blob(chunksRef.current, { type: "audio/webm" }))
        stream.getTracks().forEach((t) => t.stop())
      }
      recorderRef.current = recorder
      recorder.start()
      setBlob(null)
      setSeconds(0)
      setRecording(true)
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch {
      setDenied(true)
    }
  }

  function stop() {
    recorderRef.current?.stop()
    stopTimer()
    setRecording(false)
  }

  if (denied) {
    return (
      <p role="alert" className="px-2 py-6 text-sm text-destructive">
        Microphone access was denied. Enable it in your browser settings to
        record.
      </p>
    )
  }

  return (
    <div className="flex flex-col items-center gap-3 py-4">
      {blob && !recording ? (
        <div className="flex w-full flex-col gap-3">
          <AudioPreview
            source={blob}
            label="Recording"
            onClear={() => setBlob(null)}
          />
          <Button
            type="button"
            className="w-fit"
            onClick={() =>
              onSelect({ kind: "record", blob, label: "Recording" })
            }
          >
            Use recording
          </Button>
        </div>
      ) : (
        <>
          <span className="font-mono text-2xl tabular-nums">
            {formatDuration(seconds)}
          </span>
          {recording ? (
            <Button type="button" variant="destructive" onClick={stop}>
              <HugeiconsIcon icon={StopIcon} data-icon="inline-start" />
              Stop
            </Button>
          ) : (
            <Button type="button" onClick={start}>
              <HugeiconsIcon icon={RecordIcon} data-icon="inline-start" />
              Record
            </Button>
          )}
        </>
      )}
    </div>
  )
}
