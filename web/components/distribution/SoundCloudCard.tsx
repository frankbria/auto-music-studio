"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Alert01Icon,
  Cancel01Icon,
  CheckmarkCircle01Icon,
  Loading03Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  connectSoundCloud,
  disconnectSoundCloud,
  getSoundCloudStatus,
  type SoundCloudStatus,
} from "@/lib/distribution"
import { useAuth } from "@/hooks/use-auth"

type Phase = "loading" | "ready" | "error"
type Message = { tone: "error" | "success"; text: string } | null

/** First letters of the username, for the placeholder avatar (no avatar_url from backend). */
function initials(username: string | null): string {
  if (!username) return "SC"
  const parts = username.trim().split(/[\s_-]+/).filter(Boolean)
  const chars = (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")
  return (chars || username.slice(0, 2)).toUpperCase()
}

/** SoundCloud account linking (US-21.5): connect, show the linked account, disconnect. */
export function SoundCloudCard() {
  const { accessToken } = useAuth()
  const router = useRouter()
  const [phase, setPhase] = useState<Phase>("loading")
  const [status, setStatus] = useState<SoundCloudStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [message, setMessage] = useState<Message>(null)
  // Bumped by Retry to re-run the status effect (mirrors use-clip's mount fetch:
  // state is set only inside the promise callback, never synchronously).
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!accessToken) return
    let active = true
    getSoundCloudStatus(accessToken)
      .then((res) => {
        if (!active) return
        if (res.kind === "unauthorized") return router.push("/login")
        if (res.kind === "error") {
          setPhase("error")
          return
        }
        setStatus(res.status)
        setPhase("ready")
      })
      .catch(() => {
        if (active) setPhase("error")
      })
    return () => {
      active = false
    }
  }, [accessToken, reloadKey, router])

  async function handleConnect() {
    if (!accessToken) return
    setBusy(true)
    setMessage(null)
    const res = await connectSoundCloud(accessToken)
    if (res.kind === "ok") {
      // Leave the app for SoundCloud's consent screen; we return via the callback page.
      window.location.href = res.authorizationUrl
      return
    }
    if (res.kind === "unauthorized") return router.push("/login")
    setBusy(false)
    setMessage({
      tone: "error",
      text:
        res.kind === "unavailable"
          ? "SoundCloud connection isn't configured yet. Try again later."
          : res.detail,
    })
  }

  async function handleDisconnect() {
    if (!accessToken) return
    setBusy(true)
    setMessage(null)
    const res = await disconnectSoundCloud(accessToken)
    setConfirmOpen(false)
    setBusy(false)
    if (res.kind === "unauthorized") return router.push("/login")
    if (res.kind === "error") {
      setMessage({ tone: "error", text: res.detail })
      return
    }
    setStatus({ connected: false, username: null, connectedAt: null, tokenValid: null })
    setMessage({ tone: "success", text: "SoundCloud disconnected." })
  }

  const connected = status?.connected ?? false

  return (
    <div className="flex flex-col gap-3">
      {phase === "loading" ? (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <HugeiconsIcon icon={Loading03Icon} size={16} className="animate-spin" />
          Checking SoundCloud connection…
        </p>
      ) : phase === "error" ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load your SoundCloud status.
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setPhase("loading")
              setReloadKey((k) => k + 1)
            }}
          >
            Retry
          </Button>
        </div>
      ) : connected ? (
        <div className="flex items-center gap-3">
          <div
            aria-hidden
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-sm font-semibold text-sky-600"
          >
            {initials(status?.username ?? null)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {status?.username ?? "Connected account"}
            </p>
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <HugeiconsIcon
                icon={CheckmarkCircle01Icon}
                size={13}
                className="text-emerald-500"
              />
              Connected{status?.connectedAt ? ` · ${formatDate(status.connectedAt)}` : ""}
              {status?.tokenValid === false ? " · reauthorize to publish" : ""}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setConfirmOpen(true)}
          >
            Disconnect
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted-foreground">
            Connect your SoundCloud account to publish masters in a single click.
          </p>
          <Button size="sm" disabled={busy} onClick={handleConnect}>
            {busy ? (
              <>
                <HugeiconsIcon icon={Loading03Icon} size={16} className="animate-spin" />
                Connecting…
              </>
            ) : (
              "Connect SoundCloud"
            )}
          </Button>
        </div>
      )}

      {message && (
        <p
          role={message.tone === "error" ? "alert" : "status"}
          className={
            message.tone === "error"
              ? "flex items-center gap-1 text-sm text-destructive"
              : "flex items-center gap-1 text-sm text-emerald-600"
          }
        >
          <HugeiconsIcon
            icon={message.tone === "error" ? Alert01Icon : CheckmarkCircle01Icon}
            size={14}
          />
          {message.text}
        </p>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disconnect SoundCloud?</DialogTitle>
            <DialogDescription>
              You&apos;ll need to reconnect before you can publish to SoundCloud again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={busy}>
              <HugeiconsIcon icon={Cancel01Icon} size={16} />
              Keep connected
            </Button>
            <Button variant="destructive" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** Short, locale-independent date for the connection timestamp. */
function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}
