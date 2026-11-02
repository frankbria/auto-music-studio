import { describe, expect, it } from "vitest"

import { supportContact } from "@/lib/support"

describe("supportContact (#339)", () => {
  it("links an email address with mailto:", () => {
    expect(supportContact(" help@example.com ")).toEqual({
      href: "mailto:help@example.com",
      label: "help@example.com",
    })
  })

  it("links a web address as it is", () => {
    expect(supportContact("https://example.com/help")).toEqual({
      href: "https://example.com/help",
      label: "https://example.com/help",
    })
  })

  it.each([undefined, "", "   ", "call us", "javascript:alert(1)", "https://"])(
    "offers no link for %j",
    (value) => {
      expect(supportContact(value)).toBeNull()
    }
  )
})
