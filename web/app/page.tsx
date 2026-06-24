import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

export default function Page() {
  return (
    <main className="flex min-h-svh items-center justify-center bg-gray-50 p-6 text-gray-900">
      <div className="flex max-w-md flex-col gap-6">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-lg bg-gray-900 text-gray-50">
            <HugeiconsIcon icon={MusicNote01Icon} size={22} />
          </span>
          <h1 className="text-2xl font-bold tracking-tight">Auto Music Studio</h1>
        </div>

        <p className="leading-relaxed text-gray-600">
          Web UI scaffolded with the Nova template — Nunito Sans typography, the
          gray color palette, and Hugeicons. This placeholder confirms the design
          system renders from the first page.
        </p>

        <Button>Get started</Button>
      </div>
    </main>
  )
}
