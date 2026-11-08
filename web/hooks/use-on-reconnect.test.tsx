import { useLayoutEffect } from "react"
import { render } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { useOnReconnect } from "@/hooks/use-on-reconnect"

function Probe({
  value,
  fired,
}: {
  value: number
  fired: (value: number) => void
}) {
  useOnReconnect(() => fired(value))
  // Fires as the new render commits, before passive effects run: the window where a stale callback would answer.
  useLayoutEffect(() => {
    window.dispatchEvent(new Event("online"))
  }, [value])
  return null
}

describe("useOnReconnect", () => {
  it("runs the callback from the render that just committed", () => {
    const fired = vi.fn()
    const { rerender } = render(<Probe value={1} fired={fired} />)
    rerender(<Probe value={2} fired={fired} />)
    expect(fired).toHaveBeenLastCalledWith(2)
  })
})
