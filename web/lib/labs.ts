// Experimental features (#342): the user's view on /labs and the admin's rollout.

export type Stage = "alpha" | "beta"

export type Experiment = {
  key: string
  name: string
  description: string
  stage: Stage
  /** An admin has made it available to this user. */
  available: boolean
  /** The user switched it on, and it is available. */
  enabled: boolean
}

export type FeatureFlag = {
  key: string
  name: string
  stage: Stage
  enabled_for_everyone: boolean
  users: { id: string; email: string | null }[]
}

async function request<T>(
  url: string,
  token: string,
  method: "GET" | "PUT" | "DELETE" = "GET",
  body?: unknown
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (${res.status})`
    )
  }
  return data as T
}

export async function fetchExperiments(token: string): Promise<Experiment[]> {
  return (await request<{ experiments: Experiment[] }>("/api/labs", token))
    .experiments
}

export async function switchExperiment(
  key: string,
  enabled: boolean,
  token: string
): Promise<Experiment[]> {
  const body = await request<{ experiments: Experiment[] }>(
    `/api/labs/${encodeURIComponent(key)}`,
    token,
    "PUT",
    { enabled }
  )
  return body.experiments
}

const FLAGS = "/api/admin/feature-flags"

export async function fetchFeatureFlags(token: string): Promise<FeatureFlag[]> {
  return (await request<{ flags: FeatureFlag[] }>(FLAGS, token)).flags
}

export async function rollOutToEveryone(
  key: string,
  enabled: boolean,
  token: string
): Promise<FeatureFlag[]> {
  const body = await request<{ flags: FeatureFlag[] }>(
    `${FLAGS}/${encodeURIComponent(key)}`,
    token,
    "PUT",
    { enabled }
  )
  return body.flags
}

export async function setUserGrant(
  key: string,
  email: string,
  granted: boolean,
  token: string
): Promise<FeatureFlag[]> {
  const body = await request<{ flags: FeatureFlag[] }>(
    `${FLAGS}/${encodeURIComponent(key)}/users/${encodeURIComponent(email)}`,
    token,
    granted ? "PUT" : "DELETE"
  )
  return body.flags
}
