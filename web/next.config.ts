import path from "node:path"
import { fileURLToPath } from "node:url"
import type { NextConfig } from "next"

// import.meta.dirname is undefined on Node 20.9/20.10 (added in 20.11), which
// Next's ">=20.9.0" engine still allows — derive dirname portably instead.
const dirname = path.dirname(fileURLToPath(import.meta.url))

const nextConfig: NextConfig = {
  // Pin the workspace root to web/ so Next doesn't infer a stray parent lockfile.
  turbopack: { root: dirname },
  // Emit a self-contained server bundle (#429). Without it the runtime image has to ship
  // the whole of node_modules alongside .next; with it, the traced subset is copied into
  // the standalone output and the runtime stage installs nothing.
  output: "standalone",
}

export default nextConfig
