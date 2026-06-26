"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  DiscordIcon,
  GoogleIcon,
  Loading03Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { RETURN_TO_KEY, safeInternalPath } from "@/lib/auth"
import { useAuth } from "@/hooks/use-auth"

const PROVIDERS = [
  { id: "google", label: "Continue with Google", icon: GoogleIcon },
  { id: "discord", label: "Continue with Discord", icon: DiscordIcon },
] as const

function LoginForm() {
  const { isAuthenticated, isLoading, login } = useAuth()
  const router = useRouter()
  const searchParams = useSearchParams()
  const from = safeInternalPath(searchParams.get("from"))

  const [pending, setPending] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  // Already signed in? Skip the login screen.
  useEffect(() => {
    if (!isLoading && isAuthenticated) router.replace(from)
  }, [isLoading, isAuthenticated, from, router])

  async function handleLogin(provider: string) {
    setFailed(false)
    setPending(provider)
    try {
      // Providers don't echo app params back on the callback URL, so stash the
      // return path here for the callback page to pick up after the round-trip.
      sessionStorage.setItem(RETURN_TO_KEY, from)
      await login(provider) // navigates away to the provider on success
    } catch {
      setFailed(true)
      setPending(null)
    }
  }

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 p-8">
      <div className="flex flex-col items-center gap-1 text-center">
        <h1 className="text-2xl font-semibold">Sign in to Auto Music Studio</h1>
        <p className="text-sm text-muted-foreground">
          Start creating music in seconds.
        </p>
      </div>
      <div className="flex w-full max-w-xs flex-col gap-3">
        {PROVIDERS.map((p) => (
          <Button
            key={p.id}
            variant="outline"
            size="lg"
            className="w-full justify-center"
            disabled={pending !== null}
            onClick={() => handleLogin(p.id)}
          >
            <HugeiconsIcon
              icon={pending === p.id ? Loading03Icon : p.icon}
              size={18}
              className={pending === p.id ? "animate-spin" : undefined}
            />
            {p.label}
          </Button>
        ))}
        {failed && (
          <p role="alert" className="text-center text-sm text-destructive">
            Could not start sign-in. Please try again.
          </p>
        )}
      </div>
    </div>
  )
}

export default function LoginPage() {
  // useSearchParams requires a Suspense boundary in the App Router.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}
