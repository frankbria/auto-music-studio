/**
 * Shared dimensions and stacking order for the application shell (US-15.2).
 * Widths/heights are in pixels; the z-scale keeps the playbar above the
 * sidebar, and the sidebar above the contextual right panel.
 *
 * The matching Tailwind classes (`z-40`, `z-50`, `z-30`, `lg:` breakpoint) are
 * written literally in the components so Tailwind's scanner emits them.
 */
export const LAYOUT = {
  sidebarWidth: 64,
  sidebarExpandedWidth: 240,
  playbarHeight: 72,
  rightPanelWidth: 320,
  z: {
    rightPanel: 30,
    sidebar: 40,
    playbar: 50,
  },
} as const
