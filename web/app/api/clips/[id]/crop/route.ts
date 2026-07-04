import { clipEditRoute } from "@/lib/edit-proxy"

// Same-origin proxy for POST /api/v1/clips/{id}/crop (US-17.3).
export const POST = clipEditRoute("crop")
