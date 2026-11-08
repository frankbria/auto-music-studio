import * as Sentry from "@sentry/nextjs"

// Server-side error tracking for the web app (#342): Server Components, route handlers and the proxy. Off unless
// SENTRY_DSN is set at runtime, like the API's ACEMUSIC_API_SENTRY_DSN.
export function register() {
  Sentry.init({
    dsn: process.env.SENTRY_DSN,
    environment: process.env.SENTRY_ENVIRONMENT,
  })
}

export const onRequestError = Sentry.captureRequestError
