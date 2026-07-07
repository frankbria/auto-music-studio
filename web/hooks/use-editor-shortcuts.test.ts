import { renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useEditorShortcuts } from "./use-editor-shortcuts"

function makeActions() {
  return {
    onCut: vi.fn(),
    onCopy: vi.fn(),
    onPaste: vi.fn(),
    onDelete: vi.fn(),
    onUndo: vi.fn(),
    onRedo: vi.fn(),
  }
}

/** Dispatch a keydown on window; returns whether default was prevented. */
function press(
  key: string,
  opts: {
    ctrlKey?: boolean
    metaKey?: boolean
    shiftKey?: boolean
    target?: EventTarget
  } = {}
) {
  const e = new KeyboardEvent("keydown", {
    key,
    ctrlKey: opts.ctrlKey,
    metaKey: opts.metaKey,
    shiftKey: opts.shiftKey,
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

  it("maps Ctrl+Z to undo and Ctrl+Shift+Z / Ctrl+Y to redo", () => {
    press("z", { ctrlKey: true })
    expect(actions.onUndo).toHaveBeenCalledOnce()
    expect(actions.onRedo).not.toHaveBeenCalled()

    press("z", { ctrlKey: true, shiftKey: true })
    press("y", { ctrlKey: true })
    expect(actions.onRedo).toHaveBeenCalledTimes(2)
    // Shift+Z must not also fire undo.
    expect(actions.onUndo).toHaveBeenCalledOnce()
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
