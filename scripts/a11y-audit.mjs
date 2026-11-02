// axe-core audit of the web app (#340): every page, signed out and signed in, against WCAG 2.1 A and AA.
//
//   mkdir /tmp/a11y && cd /tmp/a11y && npm i playwright @axe-core/playwright
//   cp <repo>/scripts/a11y-audit.mjs . && echo '{"public": [], "signedIn": []}' > pages.json
//   node a11y-audit.mjs tokens.txt https://dev.automusicstudio.com
//
// tokens.txt holds one refresh token per line, minted on the target with create_refresh_token + store_refresh_token:
// each signed-in page uses its own (they rotate on use), and is flagged [NOT SIGNED IN] if it fell back to anonymous.
// CHROME_PATH picks the browser (default /usr/bin/google-chrome).
// pages.json adds pages that need an id, e.g. "/song/<clip id>". Results go to results.json beside the script.
import { readFileSync, writeFileSync } from "node:fs"
import { chromium } from "playwright"
import { AxeBuilder } from "@axe-core/playwright"

const [tokensFile, base = "https://dev.automusicstudio.com"] = process.argv.slice(2)
const tokens = readFileSync(tokensFile, "utf8").split(/\r?\n/).filter(Boolean)
const extra = JSON.parse(readFileSync(new URL("./pages.json", import.meta.url), "utf8"))

const PUBLIC = ["/", "/explore", "/search", "/search?q=harbor&sort=popular", "/feed", "/login", "/support", "/no/such/page", ...extra.public]
const SIGNED_IN = ["/create", "/studio", "/me", "/settings", "/settings/billing", "/settings/usage", "/playlists", "/notifications", "/release", ...extra.signedIn]

if (tokens.filter(Boolean).length < SIGNED_IN.length) {
  // An unauthenticated run of a signed-in page audits the login redirect and reads as clean.
  console.error(`Need ${SIGNED_IN.length} tokens, one per signed-in page; ${tokensFile} has ${tokens.length}.`)
  process.exit(1)
}

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? "/usr/bin/google-chrome",
  args: ["--no-sandbox"],
})
const results = []

async function audit(path, token) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  if (token) {
    await context.addCookies([{ name: "ams_refresh_token", value: token, url: base, httpOnly: true, secure: true }])
  }
  const page = await context.newPage()
  const calls = []
  page.on("request", (req) => calls.push(new URL(req.url()).pathname))
  await page.goto(base + path, { waitUntil: "networkidle" })
  await page.waitForTimeout(1500)
  const authed = calls.includes("/api/credits/balance")
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()
  results.push({
    path,
    signedIn: !!token,
    authed,
    finalUrl: page.url().replace(base, ""),
    violations: violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.slice(0, 4).map((n) => ({ target: n.target.join(" "), summary: n.failureSummary?.split("\n").slice(0, 3).join(" | ") })),
      count: v.nodes.length,
    })),
  })
  await context.close()
}

for (const path of PUBLIC) await audit(path)
for (const [i, path] of SIGNED_IN.entries()) await audit(path, tokens[i])
await browser.close()

writeFileSync(new URL("./results.json", import.meta.url), JSON.stringify(results, null, 2))
for (const r of results) {
  const counts = r.violations.reduce((acc, v) => ({ ...acc, [v.impact]: (acc[v.impact] ?? 0) + v.count }), {})
  const flag = r.signedIn && !r.authed ? " [NOT SIGNED IN]" : ""
  if (flag) process.exitCode = 1
  console.log(`${r.path.padEnd(32)} -> ${r.finalUrl.padEnd(24)} ${JSON.stringify(counts)}${flag}`)
}
