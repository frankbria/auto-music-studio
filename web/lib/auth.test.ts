import { describe, expect, it } from "vitest"

import {
  decodeAccessToken,
  isSupportedProvider,
  parseStateSetCookies,
  safeInternalPath,
} from "@/lib/auth"

const jwt = (payload: object) =>
  `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.sig`

describe("decodeAccessToken", () => {
  it("extracts id and email from the JWT payload", () => {
    const token = jwt({ sub: "user-123", email: "musician@example.com" })
    expect(decodeAccessToken(token)).toEqual({
      id: "user-123",
      email: "musician@example.com",
    })
  })

  it("returns null when required claims are missing", () => {
    expect(decodeAccessToken(jwt({ sub: "only-id" }))).toBeNull()
  })

  it("returns null for a malformed token", () => {
    expect(decodeAccessToken("not-a-jwt")).toBeNull()
    expect(decodeAccessToken("")).toBeNull()
  })
})

describe("parseStateSetCookies", () => {
  it("keeps only oauth_state_* names with their values, dropping attributes", () => {
    const result = parseStateSetCookies([
      "oauth_state_abc123=nonce-value; Path=/api/v1/auth; HttpOnly; Secure; SameSite=Lax",
      "other_cookie=ignored; Path=/",
    ])
    expect(result).toEqual([{ name: "oauth_state_abc123", value: "nonce-value" }])
  })

  it("skips empty-valued and malformed entries", () => {
    expect(
      parseStateSetCookies(["oauth_state_x=; Path=/", "garbage"])
    ).toEqual([])
  })
})

describe("safeInternalPath", () => {
  it("keeps a same-site absolute path", () => {
    expect(safeInternalPath("/create/advanced")).toBe("/create/advanced")
  })

  it("rejects external, protocol-relative, and relative targets", () => {
    expect(safeInternalPath("https://evil.com")).toBe("/create")
    expect(safeInternalPath("//evil.com")).toBe("/create")
    expect(safeInternalPath("/\\evil.com")).toBe("/create")
    expect(safeInternalPath("create")).toBe("/create")
    expect(safeInternalPath(null)).toBe("/create")
  })
})

describe("isSupportedProvider", () => {
  it("accepts google and discord, rejects anything else", () => {
    expect(isSupportedProvider("google")).toBe(true)
    expect(isSupportedProvider("discord")).toBe(true)
    expect(isSupportedProvider("../admin")).toBe(false)
    expect(isSupportedProvider("facebook")).toBe(false)
  })
})
