import { render, screen } from "@testing-library/react"
import { renderToStaticMarkup } from "react-dom/server"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import ErrorPage from "@/app/error"
import GlobalError from "@/app/global-error"

afterEach(() => vi.restoreAllMocks())

function crash(message: string, digest?: string) {
  return Object.assign(new Error(message), digest ? { digest } : {})
}

describe("error boundaries (#339)", () => {
  it("shows a plain message, the reference and support, never the error itself", () => {
    vi.spyOn(console, "error").mockImplementation(() => {})
    render(
      <ErrorPage
        error={crash("mongodb://admin:hunter2@db refused", "abc123")}
        reset={() => {}}
      />
    )

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong")
    expect(screen.getByText("abc123")).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "contact support" })
    ).toHaveAttribute("href", "/support")
    expect(document.body).not.toHaveTextContent("hunter2")
  })

  it("retries the page", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {})
    const reset = vi.fn()
    render(<ErrorPage error={crash("boom")} reset={reset} />)

    await userEvent.click(screen.getByRole("button", { name: "Try again" }))

    expect(reset).toHaveBeenCalledOnce()
    expect(screen.queryByText(/quote reference/)).toBeNull()
  })

  it("has a last-resort document for a broken root layout", () => {
    const html = renderToStaticMarkup(
      <GlobalError
        error={crash("layout broke: /srv/secret", "d1")}
        reset={() => {}}
      />
    )

    expect(html).toMatch(/^<html lang="en">.*<body>/)
    expect(html).toContain("Something went wrong")
    expect(html).toContain("d1")
    expect(html).not.toContain("/srv/secret")
  })
})
