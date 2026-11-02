"use client"

import { useEffect, useState } from "react"

import { FieldError } from "@/components/forms/FieldError"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  fetchFeatureFlags,
  rollOutToEveryone,
  setUserGrant,
  type FeatureFlag,
} from "@/lib/labs"

// Admin rollout of the /labs experiments (#342): on for everyone, or for named users only.

export function FeatureFlagAdmin({ token }: { token: string }) {
  const [flags, setFlags] = useState<FeatureFlag[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [emails, setEmails] = useState<Record<string, string>>({})
  const [grantErrors, setGrantErrors] = useState<Record<string, string>>({})
  // Every response carries every flag, so one change at a time: a slower response can't land last and undo a newer one.
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    fetchFeatureFlags(token).then(
      (loaded) => active && setFlags(loaded),
      () => active && setError("Couldn't load the feature flags.")
    )
    return () => {
      active = false
    }
  }, [token])

  const run = (key: string, change: Promise<FeatureFlag[]>) => {
    setSaving(true)
    change
      .then(
        (next) => {
          setFlags(next)
          setGrantErrors((errors) => ({ ...errors, [key]: "" }))
          setEmails((current) => ({ ...current, [key]: "" }))
        },
        (e: Error) =>
          setGrantErrors((errors) => ({ ...errors, [key]: e.message }))
      )
      .finally(() => setSaving(false))
  }

  if (error) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    )
  }
  if (!flags) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading feature flags…
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {flags.map((flag) => {
        const everyoneId = `flag-${flag.key}-everyone`
        const emailId = `flag-${flag.key}-email`
        return (
          <section
            key={flag.key}
            aria-label={flag.name}
            className="flex flex-col gap-3 rounded-lg border border-border p-4"
          >
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <h2 className="font-medium">{flag.name}</h2>
                <Badge
                  variant={flag.stage === "alpha" ? "destructive" : "secondary"}
                >
                  {flag.stage === "alpha" ? "Alpha" : "Beta"}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <Label htmlFor={everyoneId}>Everyone</Label>
                <Switch
                  id={everyoneId}
                  checked={flag.enabled_for_everyone}
                  disabled={saving}
                  onCheckedChange={(on) =>
                    run(flag.key, rollOutToEveryone(flag.key, on, token))
                  }
                />
              </div>
            </div>
            <ul
              aria-label={`Users granted ${flag.name}`}
              className="flex flex-col gap-1 text-sm"
            >
              {flag.users.length === 0 && (
                <li className="text-muted-foreground">
                  No users granted individually.
                </li>
              )}
              {flag.users.map((user) => (
                <li
                  key={user.id}
                  className="flex items-center justify-between gap-2"
                >
                  <span>{user.email ?? user.id}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove ${user.email ?? user.id} from ${flag.name}`}
                    disabled={saving}
                    onClick={() =>
                      user.email &&
                      run(
                        flag.key,
                        setUserGrant(flag.key, user.email, false, token)
                      )
                    }
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
            <form
              className="flex items-start gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                const email = emails[flag.key]?.trim()
                if (email)
                  run(flag.key, setUserGrant(flag.key, email, true, token))
              }}
            >
              <div className="flex flex-1 flex-col gap-1">
                <Label htmlFor={emailId} className="sr-only">
                  Grant {flag.name} to a user by email
                </Label>
                <Input
                  id={emailId}
                  type="email"
                  placeholder="user@example.com"
                  value={emails[flag.key] ?? ""}
                  onChange={(e) =>
                    setEmails((current) => ({
                      ...current,
                      [flag.key]: e.target.value,
                    }))
                  }
                  aria-invalid={!!grantErrors[flag.key]}
                  aria-describedby={
                    grantErrors[flag.key] ? `${emailId}-error` : undefined
                  }
                />
                <FieldError
                  id={`${emailId}-error`}
                  message={grantErrors[flag.key]}
                />
              </div>
              <Button type="submit" variant="outline" disabled={saving}>
                Grant
              </Button>
            </form>
          </section>
        )
      })}
    </div>
  )
}
