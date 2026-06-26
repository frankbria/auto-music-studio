import type { ReactNode } from "react"

import { LAYOUT } from "@/lib/constants/layout"
import { BottomPlaybar } from "./BottomPlaybar"
import { RightPanel } from "./RightPanel"
import { Sidebar } from "./Sidebar"

/**
 * Four-zone application shell: sidebar + main + optional right panel, with a
 * fixed bottom playbar. Wraps every route via the App Router root layout so the
 * shell (and audio playback) persists across navigation.
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
      <BottomPlaybar />
    </div>
  )
}
