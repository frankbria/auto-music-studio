import Link from "next/link"

import { Button } from "@/components/ui/button"

// Every unknown URL and every notFound() (#339): say what happened and offer the two ways back in.
export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start gap-4 p-8">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">
        This page doesn&apos;t exist, or it&apos;s no longer public.
      </p>
      <div className="flex gap-2">
        <Button asChild>
          <Link href="/">Go home</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/search">Search songs</Link>
        </Button>
      </div>
    </div>
  )
}
