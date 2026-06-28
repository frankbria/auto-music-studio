// Shared fetch wrapper for the same-origin BFF proxies. Adds an abort-based
// timeout so a stalled upstream fails closed (the caller's catch returns 502)
// instead of hanging the request indefinitely.

export async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  ms = 10_000
): Promise<Response> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), ms)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timeout)
  }
}
