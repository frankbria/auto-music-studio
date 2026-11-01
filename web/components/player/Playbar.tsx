"use client"

import { useAudioEngine } from "@/hooks/use-audio-engine"
import { usePlayerShortcuts } from "@/hooks/use-player-shortcuts"
import { LAYOUT } from "@/lib/constants/layout"

import { LikeButton } from "./LikeButton"
import { MiniWaveform } from "./MiniWaveform"
import { ModeToggles } from "./ModeToggles"
import { ProgressScrubber } from "./ProgressScrubber"
import { QueueButton, QueuePanel } from "./QueuePanel"
import { SongInfo } from "./SongInfo"
import { TransportControls } from "./TransportControls"
import { VolumeControl } from "./VolumeControl"

/**
 * The persistent player. Owns the single audio element and global shortcuts
 * (mounted once at the shell level so playback survives route changes), and
 * lays out every control across three sections.
 */
export function Playbar() {
  useAudioEngine()
  usePlayerShortcuts()

  return (
    <>
      <QueuePanel />
      <footer
        data-testid="app-playbar"
        aria-label="Player"
        style={{ height: LAYOUT.playbarHeight }}
        // z-50 written literally (matching LAYOUT.z.playbar) so Tailwind emits it.
        className="fixed inset-x-0 bottom-0 z-50 flex items-center gap-4 border-t border-border bg-background/95 px-4 backdrop-blur"
      >
        {/* Left: song info */}
        <div className="hidden w-[22%] min-w-0 sm:block">
          <SongInfo />
        </div>

        {/* Center: transport + progress */}
        <div className="flex flex-1 flex-col items-center gap-1">
          <div className="flex items-center gap-2">
            <ModeToggles />
            <TransportControls />
            <LikeButton />
          </div>
          <ProgressScrubber />
        </div>

        {/* Right: waveform + volume + queue */}
        <div className="hidden w-[22%] items-center justify-end gap-2 md:flex">
          <div className="hidden w-28 lg:block">
            <MiniWaveform />
          </div>
          <VolumeControl />
          <QueueButton />
        </div>
      </footer>
    </>
  )
}
