import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { SignInRefusedError } from "@/lib/auth"

import CallbackPage from "./page"

const completeLogin = vi.fn()

vi.mock("next/navigation", () => ({
  useParams: () => ({ provider: "google" }),
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("code=c&state=s"),
}))
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ completeLogin }) }))

describe("CallbackPage", () => {
  it("tells a suspended user how to contest the ban (#581)", async () => {
    const detail =
      "This account has been suspended. To contest it, contact appeals@example.com."
    completeLogin.mockRejectedValueOnce(new SignInRefusedError(detail))

    render(<CallbackPage />)

    expect(await screen.findByRole("alert")).toHaveTextContent(detail)
  })

  it("keeps other failures generic", async () => {
    completeLogin.mockRejectedValueOnce(new TypeError("Failed to fetch"))

    render(<CallbackPage />)

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign-in could not be completed."
    )
  })
})
