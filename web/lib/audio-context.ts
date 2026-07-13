// Shared "resolve the AudioContext constructor" fallback — Safari (and older
// WebKit) expose it as the vendor-prefixed `webkitAudioContext` instead of the
// standard `window.AudioContext`. Was duplicated across lib/audio-peaks.ts,
// lib/clip-audio-cache.ts, and hooks/use-studio-playback.ts; each call site
// keeps its own handling of an absent result (a thrown error, or none at all)
// rather than this helper inventing new behavior.
export function getAudioContextCtor() {
  return (
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext
  )
}
