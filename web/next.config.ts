import path from "node:path"
import { fileURLToPath } from "node:url"
import type { NextConfig } from "next"

// import.meta.dirname is undefined on Node 20.9/20.10 (added in 20.11), which
// Next's ">=20.9.0" engine still allows — derive dirname portably instead.
const dirname = path.dirname(fileURLToPath(import.meta.url))

/** Every path except Next's own assets and the same-origin API. */
export const PAGE_ROUTES = "/((?!_next/|api/).*)"

const nextConfig: NextConfig = {
  // Pin the workspace root to web/ so Next doesn't infer a stray parent lockfile.
  turbopack: { root: dirname },
  // Emit a self-contained server bundle (#429). Without it the runtime image has to ship
  // the whole of node_modules alongside .next; with it, the traced subset is copied into
  // the standalone output and the runtime stage installs nothing.
  output: "standalone",
  // #338: pages always revalidate. Next marks a prerendered page `s-maxage=31536000`, so a CDN would keep serving a
  // deploy's old HTML, whose chunk hashes the new build no longer has, for a year. The hashed /_next assets stay
  // `immutable`, and the BFF under /api sets its own headers.
  async headers() {
    return [
      {
        source: PAGE_ROUTES,
        headers: [{ key: "Cache-Control", value: "private, no-cache" }],
      },
    ]
  },
}

export default nextConfig
