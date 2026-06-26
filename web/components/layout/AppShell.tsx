import type { ReactNode } from "react"

import { LAYOUT } from "@/lib/constants/layout"
import { RightPanel } from "./RightPanel"
import { Sidebar } from "./Sidebar"

/**
 * Three top zones of the application shell: sidebar + main + optional right
 * panel. Reserves bottom space equal to the playbar height; the `BottomPlaybar`
 * itself is rendered as a sibling in the root layout (outside this container)
 * so its `position: fixed` stays viewport-anchored even if a future ancestor
 * here gains a `transform`/`will-change` and becomes a containing block.
 */
export function AppShell({
  children,
  rightPanel,
}: {
  children: ReactNode
  rightPanel?: ReactNode
}) {
  return (
    <div
      data-testid="app-shell"
      style={{ paddingBottom: LAYOUT.playbarHeight }}
      className="flex h-svh w-full overflow-hidden"
    >
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-background">{children}</main>
      {rightPanel ? <RightPanel>{rightPanel}</RightPanel> : null}
    </div>
  )
}
