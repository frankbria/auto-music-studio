"use client"

import { useState } from "react"
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
import { createPluginToken } from "@/lib/plugin-token"

// Issue #445: the DAW plugin's Platform panel needs a long-lived credential to
// keep itself signed in without the musician re-authenticating in the DAW. This
// mints an independent refresh token (the web session's own cookie token is
// untouched) — shown once, since the backend never returns it again.

export function PluginTokenCard({
  accessToken,
}: {
  accessToken: string | null
}) {
  const [token, setToken] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function handleCreate() {
    if (!accessToken) return
    setPending(true)
    setError(null)
    setCopied(false)
    try {
      const next = await createPluginToken(accessToken)
      setToken(next)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create a plugin token."
      )
    } finally {
      setPending(false)
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
          here — creating another token does not revoke earlier ones, and an
          unused token expires after 7 days.
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
      </CardContent>
    </Card>
  )
}
