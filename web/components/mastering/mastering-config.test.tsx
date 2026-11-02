import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MasteringConfig } from "@/components/mastering/mastering-config"

afterEach(() => vi.clearAllMocks())

describe("MasteringConfig", () => {
  it("offers all five profiles, and only Bakuage to a non-admin (#694)", () => {
    render(<MasteringConfig onStart={vi.fn()} />)
    for (const label of [
      "Streaming",
      "SoundCloud",
      "Club / DJ",
      "Vinyl",
      "Custom",
    ]) {
      expect(
        screen.getByRole("radio", { name: new RegExp(label) })
      ).toBeInTheDocument()
    }
    expect(screen.getByRole("radio", { name: /Bakuage/ })).toHaveAccessibleName(
      /2 credits/
    )
    for (const label of ["Dolby.io", "LANDR"]) {
      expect(
        screen.queryByRole("radio", { name: new RegExp(label) })
      ).not.toBeInTheDocument()
    }
  })

  it("offers the admin-only services to an admin, at their price", () => {
    render(<MasteringConfig onStart={vi.fn()} isAdmin />)
    expect(screen.getByRole("radio", { name: /LANDR/ })).toHaveAccessibleName(
      /130 credits/
    )
    expect(screen.getByRole("radio", { name: /Dolby/ })).toHaveAccessibleName(
      /11 credits/
    )
  })

  it("starts with a valid default config (streaming + bakuage, wav)", async () => {
    const onStart = vi.fn()
    const user = userEvent.setup()
    render(<MasteringConfig onStart={onStart} />)

    await user.click(screen.getByRole("button", { name: /start mastering/i }))
    expect(onStart).toHaveBeenCalledWith({
      profile: "streaming",
      service: "bakuage",
      format: "wav",
    })
  })

  it("reveals a LUFS input for the custom profile and submits it as target_lufs", async () => {
    const onStart = vi.fn()
    const user = userEvent.setup()
    render(<MasteringConfig onStart={onStart} />)

    await user.click(screen.getByRole("radio", { name: /custom/i }))
    const input = screen.getByLabelText(/target loudness/i)
    await user.clear(input)
    await user.type(input, "-9")

    await user.click(screen.getByRole("button", { name: /start mastering/i }))
    expect(onStart).toHaveBeenCalledWith({
      profile: "custom",
      service: "bakuage",
      format: "wav",
      target_lufs: -9,
    })
  })

  it("disables Start when the custom LUFS is out of range", async () => {
    const user = userEvent.setup()
    render(<MasteringConfig onStart={vi.fn()} />)

    await user.click(screen.getByRole("radio", { name: /custom/i }))
    const input = screen.getByLabelText(/target loudness/i)
    await user.clear(input)
    await user.type(input, "-3") // above the -5 ceiling

    expect(
      screen.getByRole("button", { name: /start mastering/i })
    ).toBeDisabled()
    expect(screen.getByText(/between -70 and -5/i)).toBeInTheDocument()
  })

  it("honors the disabled prop", () => {
    render(<MasteringConfig onStart={vi.fn()} disabled />)
    expect(
      screen.getByRole("button", { name: /start mastering/i })
    ).toBeDisabled()
  })
})
