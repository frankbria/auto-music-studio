import type { Track } from "@/lib/clips"

// ponytail: demo seed so the playbar is populated and every control is
// exercisable before a clip-browsing UI exists. All three point at one bundled
// sample WAV (public/demo/sample.wav). Replace with real clip loading
// (clipAudioUrl/clipArtworkUrl) when the browse/library UI lands.
export const DEMO_TRACKS: Track[] = [
  {
    id: "demo-1",
    title: "Neon Skyline",
    artist: "Auto Music Studio",
    audioUrl: "/demo/sample.wav",
    duration: 6,
  },
  {
    id: "demo-2",
    title: "Midnight Circuit",
    artist: "Auto Music Studio",
    audioUrl: "/demo/sample.wav",
    duration: 6,
  },
  {
    id: "demo-3",
    title: "Velvet Static",
    artist: "Auto Music Studio",
    audioUrl: "/demo/sample.wav",
    duration: 6,
  },
]
