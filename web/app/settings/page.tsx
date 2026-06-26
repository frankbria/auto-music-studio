"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  CheckmarkCircle01Icon,
  Loading03Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { AvatarUpload } from "@/components/settings/AvatarUpload"
import { FieldError } from "@/components/settings/FieldError"
import { StyleTagsInput } from "@/components/settings/StyleTagsInput"
import { useRequireAuth } from "@/hooks/use-require-auth"
import {
  useProfileSettings,
  type FieldErrors,
  type SaveResult,
} from "@/hooks/use-profile-settings"
import {
  BIO_MAX_LENGTH,
  validateBio,
  validateDisplayName,
  validateHandle,
  type UserProfile,
  type UserProfileUpdate,
} from "@/lib/profile"
import { fetchModels, type ModelInfo } from "@/lib/models"

type FormState = {
  display_name: string
  handle: string
  bio: string
  style_tags: string[]
  /** "" = no preference (cleared); otherwise a model key (US-16.4). */
  default_model: string
}

function toForm(p: UserProfile): FormState {
  return {
    display_name: p.display_name ?? "",
    handle: p.handle ?? "",
    bio: p.bio ?? "",
    style_tags: p.style_tags,
    default_model: p.default_model ?? "",
  }
}

function SettingsForm({
  profile,
  save,
}: {
  profile: UserProfile
  save: (update: UserProfileUpdate) => Promise<SaveResult>
}) {
  const initial = useMemo(() => toForm(profile), [profile])
  const [form, setForm] = useState<FormState>(initial)
  const [baseline, setBaseline] = useState<FormState>(initial)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [errors, setErrors] = useState<FieldErrors>({})
  const [handleHint, setHandleHint] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedOk, setSavedOk] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const isDirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(baseline),
    [form, baseline]
  )

  // Populate the default-model dropdown (US-16.4). Failure leaves it empty, so
  // the field just shows "No preference" and the rest of the form still works.
  useEffect(() => {
    let active = true
    fetchModels()
      .then((list) => {
        if (active) setModels(list)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  // Real-time (debounced) handle format feedback. Server uniqueness is only
  // known on save, surfaced as a 409 below.
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      setHandleHint(
        form.handle.length === 0 ? null : validateHandle(form.handle)
      )
    }, 400)
    return () => {
      if (debounce.current) clearTimeout(debounce.current)
    }
  }, [form.handle])

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }))
    setErrors((e) => ({ ...e, [key]: undefined }))
    setSavedOk(false)
    setFormError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const clientErrors: FieldErrors = {}
    const nameErr = validateDisplayName(form.display_name)
    if (nameErr) clientErrors.display_name = nameErr
    const handleErr = validateHandle(form.handle)
    if (handleErr) clientErrors.handle = handleErr
    const bioErr = validateBio(form.bio)
    if (bioErr) clientErrors.bio = bioErr
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors)
      return
    }

    // Send only changed fields (exclude_unset). Compare the normalized
    // (trimmed) values against the stored baseline so a trailing space alone
    // doesn't trigger a no-op PATCH, and a whitespace-only bio isn't stored.
    const trimmedName = form.display_name.trim()
    const trimmedBio = form.bio.trim()
    const payload: UserProfileUpdate = {}
    if (trimmedName !== baseline.display_name)
      payload.display_name = trimmedName
    if (form.handle !== baseline.handle)
      payload.handle = form.handle.length === 0 ? null : form.handle
    if (trimmedBio !== baseline.bio) payload.bio = trimmedBio
    if (JSON.stringify(form.style_tags) !== JSON.stringify(baseline.style_tags))
      payload.style_tags = form.style_tags
    // "" means "clear preference" → send null so the backend unsets it.
    if (form.default_model !== baseline.default_model)
      payload.default_model = form.default_model === "" ? null : form.default_model

    // Nothing actually changed once normalized — just re-sync the form to the
    // trimmed values and report success without a wasted round-trip.
    if (Object.keys(payload).length === 0) {
      const synced = { ...form, display_name: trimmedName, bio: trimmedBio }
      setForm(synced)
      setBaseline(synced)
      setSavedOk(true)
      return
    }

    setSaving(true)
    setErrors({})
    setFormError(null)
    const result = await save(payload)
    setSaving(false)
    if (result.ok) {
      const next = toForm(result.profile)
      setForm(next)
      setBaseline(next)
      setSavedOk(true)
    } else {
      setErrors(result.fieldErrors)
      setFormError(result.message)
    }
  }

  // Trimmed, to match validateBio and the submitted payload — so the counter
  // and aria-invalid never flag a bio that would actually save fine.
  const bioOver = form.bio.trim().length > BIO_MAX_LENGTH

  // Synchronous validity gates the "Looks good" hint so it can't flash on a
  // still-invalid handle during the 400 ms before the debounce settles.
  const handleValid =
    form.handle.length > 0 && validateHandle(form.handle) === null

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            This information appears on your public profile.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Disable edits while a save is in flight so a slow PATCH can't
              clobber fields the user changed after clicking Save. */}
          <fieldset
            disabled={saving}
            className="flex min-w-0 flex-col gap-5 border-0 p-0"
          >
            <div className="flex flex-col gap-2">
              <Label>Avatar</Label>
              <AvatarUpload currentUrl={profile.avatar_url} />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="display_name">Display name</Label>
              <Input
                id="display_name"
                value={form.display_name}
                onChange={(e) => update("display_name", e.target.value)}
                aria-invalid={errors.display_name ? true : undefined}
                aria-describedby={
                  errors.display_name ? "display_name-error" : undefined
                }
                maxLength={120}
              />
              <FieldError
                id="display_name-error"
                message={errors.display_name}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="handle">Handle</Label>
              <div className="relative">
                <span className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-sm text-muted-foreground">
                  @
                </span>
                <Input
                  id="handle"
                  value={form.handle}
                  onChange={(e) => update("handle", e.target.value)}
                  aria-invalid={errors.handle || handleHint ? true : undefined}
                  aria-describedby={
                    errors.handle || handleHint ? "handle-error" : undefined
                  }
                  className="pl-6"
                  placeholder="your-handle"
                />
              </div>
              <FieldError
                id="handle-error"
                message={errors.handle ?? handleHint}
              />
              {!errors.handle &&
                !formError &&
                !handleHint &&
                handleValid &&
                form.handle !== baseline.handle && (
                  <p className="flex items-center gap-1 text-sm text-muted-foreground">
                    <HugeiconsIcon icon={CheckmarkCircle01Icon} size={14} />
                    Looks good
                  </p>
                )}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="bio">Bio</Label>
              <Textarea
                id="bio"
                value={form.bio}
                onChange={(e) => update("bio", e.target.value)}
                aria-invalid={errors.bio || bioOver ? true : undefined}
                aria-describedby={
                  // Counter is always rendered, so always announce it; add the
                  // error id only when there's a submitted bio error.
                  [errors.bio ? "bio-error" : null, "bio-counter"]
                    .filter(Boolean)
                    .join(" ")
                }
                rows={4}
              />
              <div className="flex items-center justify-between">
                <FieldError id="bio-error" message={errors.bio} />
                <span
                  id="bio-counter"
                  className={
                    "ml-auto text-xs " +
                    (bioOver ? "text-destructive" : "text-muted-foreground")
                  }
                >
                  {form.bio.trim().length}/{BIO_MAX_LENGTH}
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>Style tags</Label>
              <StyleTagsInput
                tags={form.style_tags}
                onChange={(next) => update("style_tags", next)}
              />
              <FieldError message={errors.style_tags} />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="default_model">Default model</Label>
              <select
                id="default_model"
                value={form.default_model}
                onChange={(e) => update("default_model", e.target.value)}
                className="h-9 rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <option value="">No preference</option>
                {models.map((m) => (
                  <option key={m.key} value={m.key}>
                    {m.display_name}
                    {m.pro_only ? " (Pro)" : ""}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                Used as the starting model on the Create page.
              </p>
            </div>
          </fieldset>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!isDirty || saving}>
          {saving && (
            <HugeiconsIcon
              icon={Loading03Icon}
              size={16}
              className="animate-spin"
            />
          )}
          Save changes
        </Button>
        {savedOk && (
          <p role="status" className="text-sm text-muted-foreground">
            Saved.
          </p>
        )}
        {formError && (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        )}
      </div>
    </form>
  )
}

export default function SettingsPage() {
  const { isLoading: authLoading, isAuthenticated } = useRequireAuth()
  const { profile, isLoading, error, save } = useProfileSettings()

  // useRequireAuth redirects unauthenticated users; render nothing meanwhile.
  if (authLoading || !isAuthenticated) return null

  return (
    <div className="mx-auto w-full max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Settings</h1>
      {isLoading && (
        <div
          data-testid="settings-skeleton"
          className="h-64 animate-pulse rounded-xl bg-muted"
        />
      )}
      {!isLoading && error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!isLoading && !error && profile && (
        <SettingsForm profile={profile} save={save} />
      )}
    </div>
  )
}
