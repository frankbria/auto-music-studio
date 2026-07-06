import { renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useEditorShortcuts } from "./use-editor-shortcuts"

function makeActions() {
  return { onCut: vi.fn(), onCopy: vi.fn(), onPaste: vi.fn(), onDelete: vi.fn() }
}

/** Dispatch a keydown on window; returns whether default was prevented. */
function press(
  key: string,
  opts: { ctrlKey?: boolean; metaKey?: boolean; target?: EventTarget } = {}
) {
  const e = new KeyboardEvent("keydown", {
    key,
    ctrlKey: opts.ctrlKey,
    metaKey: opts.metaKey,
    cancelable: true,
    bubbles: true,
  })
  if (opts.target) Object.defineProperty(e, "target", { value: opts.target })
  window.dispatchEvent(e)
  return e.defaultPrevented
}

describe("useEditorShortcuts", () => {
  let actions: ReturnType<typeof makeActions>
  beforeEach(() => {
    actions = makeActions()
    renderHook(() => useEditorShortcuts(actions))
  })

  it("maps Ctrl+X/C/V and Delete to the right actions", () => {
    press("x", { ctrlKey: true })
    press("c", { ctrlKey: true })
    press("v", { ctrlKey: true })
    press("Delete")
    expect(actions.onCut).toHaveBeenCalledOnce()
    expect(actions.onCopy).toHaveBeenCalledOnce()
    expect(actions.onPaste).toHaveBeenCalledOnce()
    expect(actions.onDelete).toHaveBeenCalledOnce()
  })

  it("also accepts Cmd (metaKey) and Backspace", () => {
    press("x", { metaKey: true })
    press("Backspace")
    expect(actions.onCut).toHaveBeenCalledOnce()
    expect(actions.onDelete).toHaveBeenCalledOnce()
  })

  it("prevents default for bound keys only", () => {
    expect(press("x", { ctrlKey: true })).toBe(true)
    expect(press("a", { ctrlKey: true })).toBe(false) // unbound → left alone
  })

  it("ignores shortcuts while typing in an input", () => {
    const input = document.createElement("input")
    press("x", { ctrlKey: true, target: input })
    press("Delete", { target: input })
    expect(actions.onCut).not.toHaveBeenCalled()
    expect(actions.onDelete).not.toHaveBeenCalled()
  })
})
