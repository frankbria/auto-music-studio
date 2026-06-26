import { NextResponse, type NextRequest } from "next/server"

import { REFRESH_COOKIE } from "@/lib/auth"

// Gate protected routes on the presence of the session (refresh) cookie. A
// present-but-invalid token is handled client-side after the refresh attempt;
// here we only need the cheap "never signed in" redirect, with no content flash.
export function middleware(request: NextRequest) {
  if (request.cookies.has(REFRESH_COOKIE)) return NextResponse.next()

  const url = new URL("/login", request.url)
  url.searchParams.set("from", request.nextUrl.pathname)
  return NextResponse.redirect(url)
}

export const config = {
  matcher: ["/create", "/create/:path*"],
}
