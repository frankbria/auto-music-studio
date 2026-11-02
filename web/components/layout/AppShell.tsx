import type { ReactNode } from "react"

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
      style={{ paddingBottom: "var(--playbar-height)" }}
      className="flex h-svh w-full overflow-hidden"
    >
      {/* #340: the first Tab stop on every page skips the sidebar's links. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:ring-3 focus:ring-ring/50"
      >
        Skip to content
      </a>
      <Sidebar />
      <main
        id="main-content"
        tabIndex={-1}
        className="flex-1 overflow-y-auto bg-background outline-none"
      >
        {children}
      </main>
      {rightPanel ? <RightPanel>{rightPanel}</RightPanel> : null}
    </div>
  )
}
