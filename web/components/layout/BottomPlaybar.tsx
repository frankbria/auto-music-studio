import { LAYOUT } from "@/lib/constants/layout"

/**
 * Persistent player bar fixed to the viewport bottom. Stays visible during
 * scroll and renders above every other zone. Placeholder controls — real
 * playback UI arrives in US-15.6.
 */
export function BottomPlaybar() {
  return (
    <footer
      data-testid="app-playbar"
      aria-label="Player"
      style={{ height: LAYOUT.playbarHeight }}
      className="fixed inset-x-0 bottom-0 z-50 flex items-center gap-3 border-t border-border bg-background px-4"
    >
      {/* placeholder player controls — populated by US-15.6 */}
      <span className="text-sm text-muted-foreground">Player controls</span>
    </footer>
  )
}
