"use client"

import { useContext, useEffect, useState } from "react"
import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { AuthContext } from "@/contexts/auth-context"
import { fetchExperiments, switchExperiment, type Experiment } from "@/lib/labs"

// /labs (#342): experimental features, each with its stage and a switch. A feature an admin hasn't made available
// to this account shows, but its switch is off and explains why.

const STAGE_LABEL = { alpha: "Alpha", beta: "Beta" } as const

export function LabsPanel() {
  const auth = useContext(AuthContext)
  const token = auth?.accessToken ?? null
  const [experiments, setExperiments] = useState<Experiment[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    let active = true
    fetchExperiments(token).then(
      (loaded) => active && setExperiments(loaded),
      () => active && setError("Couldn't load the experiments.")
    )
    return () => {
      active = false
    }
  }, [token])

  if (!auth || (!auth.isLoading && !token)) {
    return (
      <p className="text-sm text-muted-foreground">
        <Link href="/login?from=/labs" className="underline">
          Sign in
        </Link>{" "}
        to try experimental features.
      </p>
    )
  }

  const toggle = (experiment: Experiment, enabled: boolean) => {
    if (!token) return
    setSaving(experiment.key)
    setError(null)
    switchExperiment(experiment.key, enabled, token)
      .then(setExperiments, (e: Error) => setError(e.message))
      .finally(() => setSaving(null))
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {experiments === null && !error && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading experiments…
        </p>
      )}
      {experiments?.map((experiment) => {
        const switchId = `lab-${experiment.key}`
        const hintId = `${switchId}-hint`
        return (
          <section
            key={experiment.key}
            aria-labelledby={`${switchId}-name`}
            className="flex items-start justify-between gap-4 rounded-lg border border-border p-4"
          >
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <h2 id={`${switchId}-name`} className="font-medium">
                  {experiment.name}
                </h2>
                <Badge
                  variant={
                    experiment.stage === "alpha" ? "destructive" : "secondary"
                  }
                >
                  {STAGE_LABEL[experiment.stage]}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {experiment.description}
              </p>
              {!experiment.available && (
                <p id={hintId} className="text-xs text-muted-foreground">
                  Not available to your account yet.
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Label htmlFor={switchId} className="sr-only">
                {experiment.name}
              </Label>
              <Switch
                id={switchId}
                checked={experiment.enabled}
                disabled={!experiment.available || saving === experiment.key}
                aria-describedby={experiment.available ? undefined : hintId}
                onCheckedChange={(enabled) => toggle(experiment, enabled)}
              />
            </div>
          </section>
        )
      })}
    </div>
  )
}
