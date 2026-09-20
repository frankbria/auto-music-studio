import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { PluginTokenCard } from "@/components/settings/PluginTokenCard"

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// A Response body can only be read once, and the card now makes several requests
// (list on mount, create, re-list, revoke). The handler is called per request so
// each one gets its own Response.
function stubFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>
) {
  const mock = vi.fn((url: string, init?: RequestInit) =>
    Promise.resolve(handler(url, init))
  )
  vi.stubGlobal("fetch", mock)
  return mock
}

const TOKENS = [
  {
    id: "65f1",
    created_at: "2026-09-19T12:00:00Z",
    expires_at: "2026-09-26T12:00:00Z",
  },
  {
    id: "65f2",
    created_at: "2026-09-12T12:00:00Z",
    expires_at: "2026-09-19T12:00:00Z",
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("PluginTokenCard", () => {
  it("disables the create button when there is no access token", () => {
    render(<PluginTokenCard accessToken={null} />)
    expect(
      screen.getByRole("button", { name: /create plugin token/i })
    ).toBeDisabled()
  })

  it("creates a plugin token and shows it in a read-only field", async () => {
    stubFetch((_url, init) =>
      init?.method === "POST"
        ? jsonRes({ refresh_token: "plugin-r-123" })
        : jsonRes([])
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    await user.click(
      screen.getByRole("button", { name: /create plugin token/i })
    )

    const tokenField = await screen.findByLabelText("Plugin token")
    expect(tokenField).toHaveValue("plugin-r-123")
    expect(tokenField).toHaveAttribute("readonly")
  })

  it("copies the token to the clipboard and shows feedback", async () => {
    stubFetch((_url, init) =>
      init?.method === "POST"
        ? jsonRes({ refresh_token: "plugin-r-123" })
        : jsonRes([])
    )
    // setup() installs its own clipboard stub, so ours must come after it.
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    })
    render(<PluginTokenCard accessToken="tok" />)

    await user.click(
      screen.getByRole("button", { name: /create plugin token/i })
    )
    await screen.findByLabelText("Plugin token")
    await user.click(screen.getByRole("button", { name: /^copy$/i }))

    expect(writeText).toHaveBeenCalledWith("plugin-r-123")
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /copied/i })
      ).toBeInTheDocument()
    )
  })

  it("shows an error when the request fails", async () => {
    stubFetch((_url, init) =>
      init?.method === "POST"
        ? jsonRes({ detail: "Not authenticated." }, 401)
        : jsonRes([])
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    await user.click(
      screen.getByRole("button", { name: /create plugin token/i })
    )

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /not authenticated/i
    )
  })

  it("shows a spinner while the request is pending", async () => {
    let resolveCreate: (value: Response) => void = () => {}
    stubFetch((_url, init) =>
      init?.method === "POST"
        ? new Promise<Response>((resolve) => {
            resolveCreate = resolve
          })
        : jsonRes([])
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    const button = screen.getByRole("button", { name: /create plugin token/i })
    await user.click(button)
    expect(button).toBeDisabled()

    resolveCreate(jsonRes({ refresh_token: "plugin-r-123" }))
    await screen.findByLabelText("Plugin token")
  })

  it("lists the plugin tokens that are already active", async () => {
    stubFetch(() => jsonRes(TOKENS))
    render(<PluginTokenCard accessToken="tok" />)

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /revoke token created/i })
      ).toHaveLength(2)
    )
    expect(screen.getAllByText(/^Created /)).toHaveLength(2)
    expect(screen.getAllByText(/^Expires /)).toHaveLength(2)
  })

  it("tells the musician when no plugin tokens are active", async () => {
    stubFetch(() => jsonRes([]))
    render(<PluginTokenCard accessToken="tok" />)

    expect(
      await screen.findByText(/no plugin tokens are active/i)
    ).toBeInTheDocument()
  })

  it("removes the row when a token is revoked", async () => {
    const fetchMock = stubFetch((url, init) =>
      init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : jsonRes(TOKENS)
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    const buttons = await screen.findAllByRole("button", {
      name: /revoke token created/i,
    })
    expect(buttons).toHaveLength(2)
    await user.click(buttons[0])

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /revoke token created/i })
      ).toHaveLength(1)
    )
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/plugin-tokens/65f1",
      expect.objectContaining({ method: "DELETE" })
    )
  })

  it("shows an error and keeps the row when revoking fails", async () => {
    stubFetch((_url, init) =>
      init?.method === "DELETE"
        ? jsonRes({ detail: "Plugin token not found." }, 404)
        : jsonRes(TOKENS)
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    const buttons = await screen.findAllByRole("button", {
      name: /revoke token created/i,
    })
    await user.click(buttons[0])

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /plugin token not found/i
    )
    expect(
      screen.getAllByRole("button", { name: /revoke token created/i })
    ).toHaveLength(2)
  })

  it("adds a newly created token to the list", async () => {
    let listed: unknown[] = []
    stubFetch((_url, init) => {
      if (init?.method === "POST") {
        listed = TOKENS.slice(0, 1)
        return jsonRes({ refresh_token: "plugin-r-123" })
      }
      return jsonRes(listed)
    })
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    await screen.findByText(/no plugin tokens are active/i)
    await user.click(
      screen.getByRole("button", { name: /create plugin token/i })
    )

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /revoke token created/i })
      ).toHaveLength(1)
    )
  })
})
