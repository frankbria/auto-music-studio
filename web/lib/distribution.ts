// Distribution client + guided-flow seam (US-21.5).
//
// Two halves, split by whether the backend is reachable from the current web state:
//
// 1. SoundCloud account linking is wired to the REAL backend. Its endpoints
//    (`/api/v1/distribution/soundcloud/*`) are usable without a release, so each
//    call goes through a same-origin BFF proxy under `/api/distribution/soundcloud/*`
//    that forwards the Bearer token and carries the PKCE state cookies (mirrors
//    lib/mastering + the OAuth callback BFF).
//
// 2. The guided LANDR/DistroKid flow is a local seam, like release-draft
//    ([[us-21-4-distribution-metadata-form]]) and mastering-history. The backend
//    `POST /releases/{id}/prepare/{target}` exists but needs a real release_id,
//    and the web app has no release-creation yet (only a localStorage draft). So
//    `prepareDistribution` computes the same checklist the backend would, from the
//    draft, and builds a real metadata.json package client-side. The response shape
//    mirrors the backend PrepareResponse — when release-creation lands, swap the
//    body of prepareDistribution for a fetch to the BFF prepare route and callers
//    won't change.

import { validateMetadata, type ReleaseMetadata } from "@/lib/release-draft"

// --- target catalogue -------------------------------------------------------

/** Guided targets that use the package-and-upload-manually flow. */
export type GuidedTarget = "landr" | "distrokid"

/** Every selectable distribution channel. */
export type DistributionTargetId = "soundcloud" | GuidedTarget

/** "auto" = one-click via a connected account; "guided" = prepare + manual upload. */
export type DistributionKind = "auto" | "guided"

export type DistributionTarget = {
  id: DistributionTargetId
  label: string
  kind: DistributionKind
  /** One-line pitch shown on the target card. */
  blurb: string
  /** Where the guided flow opens in a new tab (null for the automated target). */
  portalUrl: string | null
  /** Static requirements listed under each card (validation runs server-side). */
  requirements: string[]
}

const COMMON_STORE_REQUIREMENTS = [
  "Lossless master (WAV or FLAC)",
  "Square cover art, at least 3000×3000px",
  "Title, artist and genre",
  "ISRC and UPC (auto-generated if you have none)",
]

/** The three channels US-21.5 offers, in display order. */
export const DISTRIBUTION_TARGETS: DistributionTarget[] = [
  {
    id: "soundcloud",
    label: "SoundCloud",
    kind: "auto",
    blurb: "Connect your account once and publish in a single click.",
    portalUrl: null,
    requirements: [
      "Title, genre and description",
      "BPM and musical key",
      "ISRC (optional)",
      "Square artwork",
    ],
  },
  {
    id: "landr",
    label: "LANDR",
    kind: "guided",
    blurb: "Prepare a submission package, then upload it on LANDR.",
    portalUrl: "https://www.landr.com/digital-music-distribution/",
    requirements: COMMON_STORE_REQUIREMENTS,
  },
  {
    id: "distrokid",
    label: "DistroKid",
    kind: "guided",
    blurb: "Prepare a submission package, then upload it on DistroKid.",
    portalUrl: "https://distrokid.com/",
    requirements: COMMON_STORE_REQUIREMENTS,
  },
]

/** Look a target up by id (undefined if unknown). */
export function targetById(id: string): DistributionTarget | undefined {
  return DISTRIBUTION_TARGETS.find((t) => t.id === id)
}

// --- guided-flow seam -------------------------------------------------------

/** One pass/fail line in a preparation checklist (mirrors backend ChecklistItem). */
export type ChecklistItem = { item: string; passed: boolean; message: string }

/** Result of preparing a guided submission (mirrors backend PrepareResponse). */
export type PreparedPackage = {
  target: GuidedTarget
  checklist: ChecklistItem[]
  allChecksPassed: boolean
  /** Object URL of the client-built metadata.json, or null until every check passes. */
  bundleUrl: string | null
  instructions: string
}

function instructionsFor(target: GuidedTarget): string {
  const label = targetById(target)?.label ?? target
  const portal = target === "landr" ? "landr.com" : "distrokid.com"
  return [
    `Submitting to ${label}:`,
    "1. Download the package and unzip your master and artwork.",
    `2. Sign in to ${portal} and start a new release.`,
    "3. Upload the audio and cover art, and copy the fields from metadata.json.",
    `4. Submit on ${label}, then mark the release submitted here.`,
  ].join("\n")
}

/**
 * Build a guided-submission checklist for a target from the release metadata,
 * mirroring what the backend `prepare/{target}` validates. When every item
 * passes, a real metadata.json package is produced as an object URL.
 */
export function prepareDistribution(
  target: GuidedTarget,
  metadata: ReleaseMetadata
): PreparedPackage {
  const errors = validateMetadata(metadata)
  const has = (v: string) => v.trim().length > 0

  const checklist: ChecklistItem[] = [
    {
      item: "Required metadata",
      passed: !errors.title && !errors.artist && !errors.genre,
      message:
        !errors.title && !errors.artist && !errors.genre
          ? "Title, artist and genre are set."
          : "Title, artist and genre are all required.",
    },
    {
      item: "Cover art",
      passed: metadata.coverArt.kind !== "none",
      message:
        metadata.coverArt.kind !== "none"
          ? "Cover art is attached."
          : "Attach square cover art of at least 3000×3000px.",
    },
    {
      item: "ISRC",
      passed: has(metadata.isrc) && !errors.isrc,
      message: errors.isrc
        ? errors.isrc
        : has(metadata.isrc)
          ? "ISRC is set."
          : "Add an ISRC (generate one on the metadata tab).",
    },
    {
      item: "UPC",
      passed: has(metadata.upc) && !errors.upc,
      message: errors.upc
        ? errors.upc
        : has(metadata.upc)
          ? "UPC is set."
          : "Add a UPC (generate one on the metadata tab).",
    },
  ]

  const allChecksPassed = checklist.every((c) => c.passed)
  return {
    target,
    checklist,
    allChecksPassed,
    bundleUrl: allChecksPassed ? buildPackageUrl(metadata) : null,
    instructions: instructionsFor(target),
  }
}

/** Serialise the release metadata to a downloadable metadata.json object URL. */
function buildPackageUrl(metadata: ReleaseMetadata): string {
  const blob = new Blob([JSON.stringify(metadata, null, 2)], {
    type: "application/json",
  })
  return URL.createObjectURL(blob)
}

// --- SoundCloud client (real backend via BFF) -------------------------------

/** A user's SoundCloud link state (mirrors backend StatusResponse, camelCased). */
export type SoundCloudStatus = {
  connected: boolean
  username: string | null
  connectedAt: string | null
  tokenValid: boolean | null
}

const DISCONNECTED: SoundCloudStatus = {
  connected: false,
  username: null,
  connectedAt: null,
  tokenValid: null,
}

/** Shape the raw backend StatusResponse into our camelCased status. */
function toStatus(body: unknown): SoundCloudStatus {
  const b = (body ?? {}) as {
    connected?: boolean
    soundcloud_username?: string | null
    connected_at?: string | null
    token_valid?: boolean | null
  }
  return {
    connected: Boolean(b.connected),
    username: b.soundcloud_username ?? null,
    connectedAt: b.connected_at ?? null,
    tokenValid: b.token_valid ?? null,
  }
}

/** Pull a human-readable message out of a FastAPI error body. */
function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string") return detail
  }
  return fallback
}

export type StatusResult =
  | { kind: "ok"; status: SoundCloudStatus }
  | { kind: "unauthorized" }
  | { kind: "error"; detail: string }

export type ConnectResult =
  | { kind: "ok"; authorizationUrl: string }
  | { kind: "unauthorized" }
  | { kind: "unavailable"; detail: string }
  | { kind: "error"; detail: string }

export type CallbackResult =
  | { kind: "ok"; status: SoundCloudStatus }
  | { kind: "unauthorized" }
  | { kind: "invalid" }
  | { kind: "error"; detail: string }

export type DisconnectResult =
  | { kind: "ok" }
  | { kind: "unauthorized" }
  | { kind: "error"; detail: string }

function authHeaders(accessToken: string): HeadersInit {
  return { authorization: `Bearer ${accessToken}` }
}

/** Fetch the current SoundCloud link status through the BFF proxy. */
export async function getSoundCloudStatus(accessToken: string): Promise<StatusResult> {
  let res: Response
  try {
    res = await fetch("/api/distribution/soundcloud/status", {
      headers: authHeaders(accessToken),
    })
  } catch {
    return { kind: "error", detail: "Could not reach SoundCloud. Please try again." }
  }
  if (res.status === 401) return { kind: "unauthorized" }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    return { kind: "error", detail: extractDetail(body, "Could not load SoundCloud status.") }
  }
  // 404 is impossible here (status always 200 with connected:false), so any ok
  // body is a status. A blank body degrades to disconnected rather than erroring.
  const body = await res.json().catch(() => DISCONNECTED)
  return { kind: "ok", status: toStatus(body) }
}

/** Begin the OAuth link: returns the SoundCloud authorize URL to redirect to. */
export async function connectSoundCloud(accessToken: string): Promise<ConnectResult> {
  let res: Response
  try {
    res = await fetch("/api/distribution/soundcloud/connect", {
      method: "POST",
      headers: authHeaders(accessToken),
    })
  } catch {
    return { kind: "error", detail: "Could not start the SoundCloud connection." }
  }
  if (res.status === 401) return { kind: "unauthorized" }
  const body = await res.json().catch(() => ({}))
  if (res.status === 503) {
    return { kind: "unavailable", detail: extractDetail(body, "SoundCloud is not configured.") }
  }
  if (!res.ok || !(body as { authorization_url?: string }).authorization_url) {
    return { kind: "error", detail: extractDetail(body, "Could not start the SoundCloud connection.") }
  }
  return { kind: "ok", authorizationUrl: (body as { authorization_url: string }).authorization_url }
}

/** Complete the OAuth link by exchanging the code+state through the BFF proxy. */
export async function completeSoundCloudCallback(
  code: string,
  state: string,
  accessToken: string
): Promise<CallbackResult> {
  let res: Response
  try {
    res = await fetch("/api/distribution/soundcloud/callback", {
      method: "POST",
      headers: { "content-type": "application/json", ...authHeaders(accessToken) },
      body: JSON.stringify({ code, state }),
    })
  } catch {
    return { kind: "error", detail: "Could not complete the SoundCloud connection." }
  }
  if (res.status === 401) return { kind: "unauthorized" }
  if (res.status === 400) return { kind: "invalid" }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    return { kind: "error", detail: extractDetail(body, "Could not complete the SoundCloud connection.") }
  }
  return { kind: "ok", status: toStatus(body) }
}

/** Unlink the SoundCloud account through the BFF proxy (idempotent). */
export async function disconnectSoundCloud(accessToken: string): Promise<DisconnectResult> {
  let res: Response
  try {
    res = await fetch("/api/distribution/soundcloud/connect", {
      method: "DELETE",
      headers: authHeaders(accessToken),
    })
  } catch {
    return { kind: "error", detail: "Could not disconnect SoundCloud. Please try again." }
  }
  if (res.status === 401) return { kind: "unauthorized" }
  if (!res.ok && res.status !== 204) {
    const body = await res.json().catch(() => ({}))
    return { kind: "error", detail: extractDetail(body, "Could not disconnect SoundCloud.") }
  }
  return { kind: "ok" }
}
