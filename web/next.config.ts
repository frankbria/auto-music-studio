import path from "node:path"
import { fileURLToPath } from "node:url"
import type { NextConfig } from "next"

// import.meta.dirname is undefined on Node 20.9/20.10 (added in 20.11), which
// Next's ">=20.9.0" engine still allows — derive dirname portably instead.
const dirname = path.dirname(fileURLToPath(import.meta.url))

const nextConfig: NextConfig = {
  // Pin the workspace root to web/ so Next doesn't infer a stray parent lockfile.
  turbopack: { root: dirname },
}

export default nextConfig
