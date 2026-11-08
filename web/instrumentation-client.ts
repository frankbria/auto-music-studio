import * as Sentry from "@sentry/nextjs"

// Browser error tracking (#342). Off unless the image was built with NEXT_PUBLIC_SENTRY_DSN. One image serves
// staging and production, so the environment comes from the host rather than the build.
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: typeof window === "undefined" ? undefined : window.location.hostname,
})

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart
