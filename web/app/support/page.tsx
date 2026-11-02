import type { Metadata } from "next"
import Link from "next/link"

import { supportContact } from "@/lib/support"

// Read per request: the contact is deployment configuration, not something to bake into the build (#339).
export const dynamic = "force-dynamic"

export const metadata: Metadata = { title: "Support · Auto Music Studio" }

export default function SupportPage() {
  const contact = supportContact()
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4 p-8">
      <h1 className="text-2xl font-semibold">Get help</h1>
      {contact ? (
        <p>
          Contact us at{" "}
          <a href={contact.href} className="font-medium underline">
            {contact.label}
          </a>
          . If you saw an error, include the reference it showed, so we can find
          what happened.
        </p>
      ) : (
        <p>
          Contact the team that runs this site. If you saw an error, include the
          reference it showed, so they can find what happened.
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        <Link href="/" className="underline">
          Back to home
        </Link>
      </p>
    </div>
  )
}
