"use client"

import { useEffect, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  createPluginToken,
  listPluginTokens,
  revokePluginToken,
  type PluginTokenSummary,
} from "@/lib/plugin-token"

// Issue #445: the DAW plugin's Platform panel needs a long-lived credential to
// keep itself signed in without the musician re-authenticating in the DAW. This
// mints an independent refresh token (the web session's own cookie token is
// untouched) — shown once, since the backend never returns it again.
//
// Issue #515: minting was write-only, so a token pasted into a DAW on a machine
// the musician no longer has could not be taken back. The card now lists the
// live tokens and revokes them one by one.

// Date *and* time: tokens made on the same day are otherwise three identical
// rows, and the date is the only thing telling the musician which one to revoke.
function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? "unknown"
    : date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
}

export function PluginTokenCard({
  accessToken,
}: {
  accessToken: string | null
}) {
  const [token, setToken] = useState<string | null>(null)
  // null means "not loaded yet" — distinct from the loaded-and-empty state, so
  // the "no tokens" line does not flash before the first response arrives.
  const [tokens, setTokens] = useState<PluginTokenSummary[] | null>(null)
  const [pending, setPending] = useState(false)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!accessToken) return
    let cancelled = false
    // State is set from the promise continuation, never in the effect body —
    // `react-hooks/set-state-in-effect` is an error in this repo.
    listPluginTokens(accessToken)
      .then((next) => {
        if (!cancelled) setTokens(next)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(
          err instanceof Error
            ? err.message
            : "Could not load your plugin tokens."
        )
      })
    return () => {
      cancelled = true
    }
  }, [accessToken])

  async function handleCreate() {
    if (!accessToken) return
    setPending(true)
    setError(null)
    setCopied(false)
    try {
      const next = await createPluginToken(accessToken)
      setToken(next)
      // A failed re-list must not read as a failed create: the token above is
      // the only copy the musician will ever see, so the list stays stale
      // rather than the success turning into an error.
      try {
        setTokens(await listPluginTokens(accessToken))
      } catch {
        /* keep the list as it was */
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create a plugin token."
      )
    } finally {
      setPending(false)
    }
  }

  async function handleRevoke(id: string) {
    if (!accessToken) return
    setRevoking(id)
    setError(null)
    try {
      await revokePluginToken(accessToken, id)
      setTokens((prev) => (prev ?? []).filter((t) => t.id !== id))
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not revoke that plugin token."
      )
    } finally {
      setRevoking(null)
    }
  }

  async function handleCopy() {
    if (!token) return
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
    } catch {
      setError("Could not copy to the clipboard.")
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>DAW plugin token</CardTitle>
        <CardDescription>
          Paste this into the Token field of the plugin&apos;s Platform panel.
          The plugin uses it to keep itself signed in. It is shown only once
          here — creating another token leaves earlier ones working until you
          revoke them below, and an unused token expires after 7 days.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {token ? (
          <div className="flex gap-2">
            <Input
              aria-label="Plugin token"
              value={token}
              readOnly
              className="font-mono"
            />
            <Button type="button" variant="outline" onClick={handleCopy}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            disabled={pending || !accessToken}
            onClick={handleCreate}
          >
            {pending && (
              <HugeiconsIcon
                icon={Loading03Icon}
                size={16}
                className="animate-spin"
              />
            )}
            Create plugin token
          </Button>
        )}

        {tokens !== null &&
          (tokens.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No plugin tokens are active.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {tokens.map((t) => (
                <li
                  key={t.id}
                  className="flex items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <div className="text-sm">
                    <p>Created {formatDate(t.created_at)}</p>
                    <p className="text-muted-foreground">
                      Expires {formatDate(t.expires_at)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    aria-label={`Revoke token created ${formatDate(t.created_at)}`}
                    disabled={revoking !== null}
                    onClick={() => handleRevoke(t.id)}
                  >
                    {revoking === t.id && (
                      <HugeiconsIcon
                        icon={Loading03Icon}
                        size={16}
                        className="animate-spin"
                      />
                    )}
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          ))}
      </CardContent>
    </Card>
  )
}
