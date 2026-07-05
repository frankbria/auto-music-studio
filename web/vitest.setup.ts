import "@testing-library/jest-dom/vitest"
import { afterEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"

import { routerMock } from "./test/router-mock"

// One shared router instance so a test capturing `const { push } = useRouter()`
// holds the same spy the component calls.
const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
}

vi.mock("next/navigation", () => ({
  usePathname: () => routerMock.pathname,
  useRouter: () => mockRouter,
}))

// jsdom lacks the pointer-capture / scroll APIs Radix uses when opening menus.
const proto = window.Element.prototype as unknown as Record<string, unknown>
proto.hasPointerCapture ??= () => false
proto.setPointerCapture ??= () => {}
proto.releasePointerCapture ??= () => {}
proto.scrollIntoView ??= () => {}

// jsdom lacks ResizeObserver, which Radix's Slider observes on mount (US-17.3).
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

afterEach(() => {
  cleanup()
  routerMock.pathname = "/"
  vi.clearAllMocks()
  // The player store persists likes/dislikes to localStorage; clear it so state
  // doesn't leak between tests (US-17.6 added the dislike slice).
  window.localStorage.clear()
})
