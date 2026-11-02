// Mobile audit (#341): each page at a phone width, with touch emulation (so `pointer: coarse` applies). Reports
// horizontal overflow and every interactive element under 44x44, and screenshots each page.
//
//   Set up as for scripts/a11y-audit.mjs (same folder, tokens file and pages.json), then
//   node mobile-audit.mjs tokens.txt 360 https://dev.automusicstudio.com
//
// Exempt and expected in the list: "Skip to content" (1x1 until focused) and links inside a sentence.
import { readFileSync, writeFileSync } from "node:fs"
import { chromium } from "playwright"

const [tokensFile, width = "360", base = "https://dev.automusicstudio.com"] = process.argv.slice(2)
const tokens = readFileSync(tokensFile, "utf8").split(/\r?\n/).filter(Boolean)
const extra = JSON.parse(readFileSync(new URL("./pages.json", import.meta.url), "utf8"))
const PUBLIC = ["/", "/explore", "/search?q=harbor", "/feed", "/login", "/support", ...extra.public]
const SIGNED_IN = ["/create", "/studio", "/me", "/settings", "/settings/billing", "/playlists", "/notifications", "/release", ...extra.signedIn]

if (tokens.length < SIGNED_IN.length) {
  // An unauthenticated run of a signed-in page measures the login redirect and reads as clean.
  console.error(`Need ${SIGNED_IN.length} tokens, one per signed-in page; ${tokensFile} has ${tokens.length}.`)
  process.exit(1)
}

const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH ?? "/usr/bin/google-chrome", args: ["--no-sandbox"] })
const out = []
async function check(path, token, i) {
  const context = await browser.newContext({ viewport: { width: Number(width), height: 740 }, isMobile: true, hasTouch: true })
  if (token) await context.addCookies([{ name: "ams_refresh_token", value: token, url: base, httpOnly: true, secure: true }])
  const page = await context.newPage()
  const calls = []
  page.on("request", (req) => calls.push(new URL(req.url()).pathname))
  await page.goto(base + path, { waitUntil: "networkidle" })
  await page.waitForTimeout(1200)
  const report = await page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth - window.innerWidth
    const small = []
    for (const el of document.querySelectorAll("a[href], button, input, select, textarea, [role=button], [role=tab], [role=slider], [role=switch]")) {
      const r = el.getBoundingClientRect()
      if (!r.width || !r.height || getComputedStyle(el).visibility === "hidden") continue
      // A small control may carry a larger invisible touch area on an absolutely positioned ::after.
      const after = getComputedStyle(el, "::after")
      const enlarged = after.position === "absolute" && after.content !== "none"
      const width = Math.max(r.width, enlarged ? parseFloat(after.width) || 0 : 0)
      const height = Math.max(r.height, enlarged ? parseFloat(after.height) || 0 : 0)
      if (width < 44 || height < 44) {
        small.push(`${el.tagName.toLowerCase()}[${(el.getAttribute("aria-label") || el.textContent || el.getAttribute("type") || "").trim().slice(0, 24)}] ${Math.round(width)}x${Math.round(height)}`)
      }
    }
    const wide = [...document.querySelectorAll("body *")]
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")}`)
    return { overflow, small, wide }
  })
  await page.screenshot({ path: new URL(`./m${width}-${i}.png`, import.meta.url).pathname })
  out.push({ path, signedIn: !!token, authed: calls.includes("/api/credits/balance"), ...report })
  await context.close()
}
let i = 0
for (const p of PUBLIC) await check(p, undefined, i++)
for (const [n, p] of SIGNED_IN.entries()) await check(p, tokens[n], i++)
await browser.close()
writeFileSync(new URL(`./mobile-${width}.json`, import.meta.url), JSON.stringify(out, null, 2))
for (const r of out) {
  const flag = r.signedIn && !r.authed ? " [NOT SIGNED IN]" : ""
  if (flag) process.exitCode = 1
  console.log(`${r.path.padEnd(34)} overflow=${r.overflow}px small=${r.small.length} ${r.wide.slice(0, 2).join(" ")}${flag}`)
}
