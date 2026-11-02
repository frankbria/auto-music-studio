import type { Metadata } from "next"

import { LabsPanel } from "@/components/labs/LabsPanel"

export const metadata: Metadata = { title: "Labs · Auto Music Studio" }

// Experimental features (#342): Alpha ones may break, Beta ones are nearly ready. An admin chooses who can try each.
export default function LabsPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Labs</h1>
        <p className="text-sm text-muted-foreground">
          Try features we&apos;re still building. Alpha features may change or
          break; Beta features are nearly ready.
        </p>
      </div>
      <LabsPanel />
    </div>
  )
}
