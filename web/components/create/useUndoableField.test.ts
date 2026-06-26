import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { useUndoableField, UNDO_HISTORY_MAX } from "@/components/create/useUndoableField"

describe("useUndoableField", () => {
  it("starts at the initial value with nothing to undo", () => {
    const { result } = renderHook(() => useUndoableField("hello"))
    expect(result.current.value).toBe("hello")
    expect(result.current.canUndo).toBe(false)
  })

  it("setValue updates the value and enables undo", () => {
    const { result } = renderHook(() => useUndoableField(""))
    act(() => result.current.setValue("a"))
    expect(result.current.value).toBe("a")
    expect(result.current.canUndo).toBe(true)
  })

  it("undo reverts to the previous value", () => {
    const { result } = renderHook(() => useUndoableField("start"))
    act(() => result.current.setValue("one"))
    act(() => result.current.setValue("two"))
    act(() => result.current.undo())
    expect(result.current.value).toBe("one")
    act(() => result.current.undo())
    expect(result.current.value).toBe("start")
    expect(result.current.canUndo).toBe(false)
  })

  it("undo at the initial state is a no-op", () => {
    const { result } = renderHook(() => useUndoableField("x"))
    act(() => result.current.undo())
    expect(result.current.value).toBe("x")
  })

  it("ignores a setValue equal to the current value", () => {
    const { result } = renderHook(() => useUndoableField("same"))
    act(() => result.current.setValue("same"))
    expect(result.current.canUndo).toBe(false)
  })

  it("caps history depth so undo cannot exceed the limit", () => {
    const { result } = renderHook(() => useUndoableField("0"))
    for (let i = 1; i <= UNDO_HISTORY_MAX + 5; i++) {
      act(() => result.current.setValue(String(i)))
    }
    // Undo all the way down; the floor value is whatever survived the cap, never older.
    for (let i = 0; i < UNDO_HISTORY_MAX + 10; i++) {
      act(() => result.current.undo())
    }
    expect(result.current.canUndo).toBe(false)
    expect(result.current.value).not.toBe("0") // the original was evicted by the cap
  })
})
