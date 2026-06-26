import { Playbar } from "@/components/player/Playbar"

/**
 * Persistent player bar fixed to the viewport bottom. The real playback UI
 * lives in `components/player/Playbar` (US-15.6); this thin wrapper keeps the
 * shell's layout slot stable.
 */
export function BottomPlaybar() {
  return <Playbar />
}
