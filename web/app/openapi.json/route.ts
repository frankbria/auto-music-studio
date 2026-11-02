import { forwardApiDocs } from "@/lib/api-docs-proxy"

// The OpenAPI schema the /docs page renders (#342).
export async function GET() {
  return forwardApiDocs("/openapi.json")
}
