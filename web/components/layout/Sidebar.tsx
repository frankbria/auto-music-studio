import { LAYOUT } from "@/lib/constants/layout"

/**
 * Collapsed icon bar on the left edge of the shell. Placeholder icon slots —
 * real navigation arrives in US-15.3. Stays a fixed 64px at every breakpoint.
 */
export function Sidebar() {
  return (
    <aside
      data-testid="app-sidebar"
      aria-label="Primary navigation"
      style={{ width: LAYOUT.sidebarWidth }}
      className="z-40 flex h-full shrink-0 flex-col items-center gap-4 border-r border-border bg-sidebar py-4"
    >
      {/* placeholder icon slots — populated by US-15.3 */}
      {Array.from({ length: 4 }).map((_, i) => (
        <span
          key={i}
          className="size-8 rounded-md bg-sidebar-accent"
          aria-hidden
        />
      ))}
    </aside>
  )
}
