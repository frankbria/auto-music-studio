import type { ReactNode } from "react"

import { LAYOUT } from "@/lib/constants/layout"

/**
 * Contextual panel on the right edge. Fixed 320px, hidden below the lg
 * (1024px) breakpoint so the layout stays usable at the minimum supported
 * width. Rendered only when the shell is given contextual content.
 */
export function RightPanel({ children }: { children?: ReactNode }) {
  return (
    <aside
      data-testid="app-right-panel"
      aria-label="Contextual panel"
      style={{ width: LAYOUT.rightPanelWidth }}
      className="z-30 hidden h-full shrink-0 flex-col border-l border-border bg-background p-4 lg:flex"
    >
      {children ?? (
        <p className="text-sm text-muted-foreground">contextual content area</p>
      )}
    </aside>
  )
}
