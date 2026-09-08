import { afterEach, describe, expect, it, vi } from "vitest"

import { fetchCurrentProfile } from "@/lib/profile-request"

function profileRes(tier: string, status = 200) {
  return new Response(JSON.stringify({ subscription_tier: tier }), { status })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("fetchCurrentProfile (#402)", () => {
  it("sends the Bearer token with a bounded signal and resolves the parsed profile", async () => {
    const fetchMock = vi.fn().mockResolvedValue(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    const profile = await fetchCurrentProfile("tok")

    expect(profile.subscription_tier).toBe("pro")
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/users/me")
    expect((opts.headers as Record<string, string>).authorization).toBe(
      "Bearer tok"
    )
    expect(opts.signal).toBeInstanceOf(AbortSignal)
  })

  it("shares one request between concurrent callers with the same token", async () => {
    let release: (res: Response) => void = () => {}
    const gate = new Promise<Response>((resolve) => {
      release = resolve
    })
    const fetchMock = vi.fn(() => gate)
    vi.stubGlobal("fetch", fetchMock)

    const first = fetchCurrentProfile("tok")
    const second = fetchCurrentProfile("tok")
    expect(fetchMock).toHaveBeenCalledTimes(1)

    release(profileRes("pro"))
    const [a, b] = await Promise.all([first, second])
    expect(a.subscription_tier).toBe("pro")
    // Same parsed profile, not two reads of one body.
    expect(b).toBe(a)
  })

  it("does not share a request across different tokens", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(profileRes("free"))
      .mockResolvedValueOnce(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    const [a, b] = await Promise.all([
      fetchCurrentProfile("tok-a"),
      fetchCurrentProfile("tok-b"),
    ])

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(a.subscription_tier).toBe("free")
    expect(b.subscription_tier).toBe("pro")
  })

  it("fetches again once the shared request has settled, so nothing is cached", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(profileRes("free"))
      .mockResolvedValueOnce(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    expect((await fetchCurrentProfile("tok")).subscription_tier).toBe("free")
    // An upgrade between the two calls is picked up by the second one.
    expect((await fetchCurrentProfile("tok")).subscription_tier).toBe("pro")
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it("rejects every sharer on a non-OK status and lets the next call try again", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(profileRes("pro", 500))
      .mockResolvedValueOnce(profileRes("pro"))
    vi.stubGlobal("fetch", fetchMock)

    const first = fetchCurrentProfile("tok")
    const second = fetchCurrentProfile("tok")
    await expect(first).rejects.toThrow(/500/)
    await expect(second).rejects.toThrow(/500/)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await expect(fetchCurrentProfile("tok")).resolves.toMatchObject({
      subscription_tier: "pro",
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
