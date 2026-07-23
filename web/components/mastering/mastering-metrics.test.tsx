import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MasteringMetrics } from "@/components/mastering/mastering-metrics"

afterEach(() => vi.clearAllMocks())

describe("MasteringMetrics", () => {
  it("shows a fallback when no metrics are present", () => {
    render(<MasteringMetrics metrics={undefined} />)
    expect(screen.getByText(/metrics not available/i)).toBeInTheDocument()
  })

  it("shows loudness with a signed delta vs. original", () => {
    render(<MasteringMetrics metrics={{ loudness: -14 }} loudnessDelta={6} />)
    expect(screen.getByText(/-14\.0 LUFS/)).toBeInTheDocument()
    expect(screen.getByText(/\+6\.0 dB vs\. original/)).toBeInTheDocument()
  })

  it("renders an EQ visualization when bands are present", () => {
    const bands = Array.from({ length: 16 }, (_, i) => i - 8)
    render(<MasteringMetrics metrics={{ loudness: -14, eq_bands: bands }} />)
    expect(screen.getByRole("img", { name: /equalizer, 16 bands/i })).toBeInTheDocument()
  })

  it("degrades gracefully for a loudness-only service (no EQ, no stereo)", () => {
    render(<MasteringMetrics metrics={{ loudness: -12 }} />)
    expect(screen.getByText(/-12\.0 LUFS/)).toBeInTheDocument()
    expect(screen.queryByRole("img")).not.toBeInTheDocument()
    expect(screen.queryByText(/stereo image/i)).not.toBeInTheDocument()
  })

  it("shows stereo image when provided", () => {
    render(<MasteringMetrics metrics={{ loudness: -14, stereo_width: 0.8, stereo_balance: 0.1 }} />)
    expect(screen.getByText(/stereo image/i)).toBeInTheDocument()
    expect(screen.getByText(/width 0\.80/)).toBeInTheDocument()
  })
})
