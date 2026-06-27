// Model registry types + client for the creation-mode model selector (US-16.4).
// Mirrors the backend ModelInfo schema (src/acemusic/api/routers/models.py).
// The list is public, so fetchModels() goes through the unauthenticated BFF
// proxy at /api/models.

/** One selectable model variant, as returned by GET /api/v1/models. */
export type ModelInfo = {
  key: string
  display_name: string
  category: string
  description: string
  pro_only: boolean
  vram: string
  steps: string
  dit_size: string
}

/** The fallback selection when a user has no saved default model preference. */
export const DEFAULT_MODEL_KEY = "base"

/** Fetch the available models through the same-origin BFF proxy. */
export async function fetchModels(): Promise<ModelInfo[]> {
  const res = await fetch("/api/models", {
    headers: { accept: "application/json" },
  })
  if (!res.ok) throw new Error("Failed to load models")
  const body = (await res.json()) as { models?: ModelInfo[] }
  return body.models ?? []
}

/** Group models by category, preserving first-seen category order. */
export function groupByCategory(models: ModelInfo[]): [string, ModelInfo[]][] {
  const groups = new Map<string, ModelInfo[]>()
  for (const m of models) {
    const list = groups.get(m.category)
    if (list) list.push(m)
    else groups.set(m.category, [m])
  }
  return [...groups.entries()]
}
