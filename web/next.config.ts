import path from "node:path"
import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // Pin the workspace root to web/ so Next doesn't infer a stray parent lockfile.
  turbopack: { root: path.resolve(import.meta.dirname) },
}

export default nextConfig
