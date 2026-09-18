import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { PluginTokenCard } from "@/components/settings/PluginTokenCard"

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ refresh_token: "plugin-r-123" }))
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ refresh_token: "plugin-r-123" }))
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonRes({ detail: "Not authenticated." }, 401))
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
    let resolveFetch: (value: Response) => void = () => {}
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          resolveFetch = resolve
        })
      )
    )
    const user = userEvent.setup()
    render(<PluginTokenCard accessToken="tok" />)

    const button = screen.getByRole("button", { name: /create plugin token/i })
    await user.click(button)
    expect(button).toBeDisabled()

    resolveFetch(jsonRes({ refresh_token: "plugin-r-123" }))
    await screen.findByLabelText("Plugin token")
  })
})
