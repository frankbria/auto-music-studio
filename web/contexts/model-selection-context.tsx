"use client"

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"

import { useAuth } from "@/hooks/use-auth"
import { DEFAULT_MODEL_KEY, fetchModels, type ModelInfo } from "@/lib/models"
import type { UserProfile } from "@/lib/profile"

// Session-scoped model selection (US-16.4). Mounted at the Create page so the
// chosen model persists across the Simple/Advanced/Sounds tabs (the selector
// lives outside the Tabs, so its state survives tab switches). Deliberately NOT
// persisted to localStorage — the requirement is "within the same session".

type ModelSelectionValue = {
  models: ModelInfo[]
  selectedModel: string
  setSelectedModel: (key: string) => void
  /** Subscription tier of the current user ("free" until the profile loads). */
  subscriptionTier: string
  isLoading: boolean
}

const ModelSelectionContext = createContext<ModelSelectionValue | null>(null)

export function ModelSelectionProvider({ children }: { children: ReactNode }) {
  const { accessToken, isLoading: authLoading } = useAuth()
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModelState] = useState<string>(DEFAULT_MODEL_KEY)
  const [subscriptionTier, setSubscriptionTier] = useState("free")
  // Two independent fetches gate readiness: the public models list and the
  // profile (which seeds the saved default). isLoading stays true until BOTH
  // settle so a user with a saved default can't submit "base" in the window
  // before the profile arrives — consumers disable submission while loading.
  const [modelsLoading, setModelsLoading] = useState(true)
  const [seedResolved, setSeedResolved] = useState(false)
  // Once the user picks a model, a late-arriving profile default must not clobber
  // their choice — this guards the default-seeding effect.
  const userTouched = useRef(false)

  const setSelectedModel = (key: string) => {
    userTouched.current = true
    setSelectedModelState(key)
  }

  // Fetch the public models list once on mount.
  useEffect(() => {
    let active = true
    fetchModels()
      .then((list) => {
        if (active) setModels(list)
      })
      .catch(() => {
        // Leave models empty; the selector renders a graceful empty state.
      })
      .finally(() => {
        if (active) setModelsLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  // Seed the initial selection from the user's saved default_model (and read
  // their tier for Pro-lock display). Skipped if the user already picked one.
  // The no-token case is handled in the isLoading derivation below (no seeding
  // to wait for), so this effect only runs the authenticated fetch.
  useEffect(() => {
    if (authLoading || !accessToken) return
    let active = true
    fetch("/api/users/me", {
      headers: { authorization: `Bearer ${accessToken}` },
    })
      .then(async (res) => (res.ok ? ((await res.json()) as UserProfile) : null))
      .then((profile) => {
        if (!active || !profile) return
        setSubscriptionTier(profile.subscription_tier)
        if (!userTouched.current && profile.default_model) {
          setSelectedModelState(profile.default_model)
        }
      })
      .catch(() => {
        // No profile → keep the fallback default and "free" tier.
      })
      .finally(() => {
        if (active) setSeedResolved(true)
      })
    return () => {
      active = false
    }
  }, [accessToken, authLoading])

  // Loading until the models list settles and — when there's a user whose saved
  // default could still arrive — the profile seed resolves. With no token (auth
  // settled) there's no default to wait for, so only the models gate applies.
  const isLoading =
    authLoading || modelsLoading || (!!accessToken && !seedResolved)

  return (
    <ModelSelectionContext.Provider
      value={{ models, selectedModel, setSelectedModel, subscriptionTier, isLoading }}
    >
      {children}
    </ModelSelectionContext.Provider>
  )
}

/** Access the model selection context. Throws if used outside the provider. */
export function useModelSelection(): ModelSelectionValue {
  const ctx = useContext(ModelSelectionContext)
  if (!ctx)
    throw new Error("useModelSelection must be used within a ModelSelectionProvider")
  return ctx
}
