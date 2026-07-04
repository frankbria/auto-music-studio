import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { EditModalShell } from "@/components/song/modals/EditModalShell"
import { RangeSelector } from "@/components/song/modals/RangeSelector"
import { StyleTextarea } from "@/components/song/modals/StyleTextarea"
import { TimeDurationInput } from "@/components/song/modals/TimeDurationInput"

describe("StyleTextarea", () => {
  it("shows a live character counter and forwards edits", async () => {
    const onChange = vi.fn()
    render(
      <StyleTextarea label="Style" value="lofi" onChange={onChange} maxLength={100} />
    )
    expect(screen.getByText("4/100")).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Style"), "!")
    expect(onChange).toHaveBeenCalledWith("lofi!")
  })

  it("flags going over the limit", () => {
    render(<StyleTextarea label="Style" value="abcdef" onChange={vi.fn()} maxLength={3} />)
    expect(screen.getByText("6/3")).toHaveClass("text-destructive")
    expect(screen.getByLabelText("Style")).toHaveAttribute("aria-invalid", "true")
  })

  it("hard-caps input via the native maxLength attribute", () => {
    render(<StyleTextarea label="Lyrics" value="" onChange={vi.fn()} maxLength={5000} />)
    expect(screen.getByLabelText("Lyrics")).toHaveAttribute("maxlength", "5000")
  })
})

describe("TimeDurationInput", () => {
  it("previews a parsed value and forwards edits", async () => {
    const onChange = vi.fn()
    render(<TimeDurationInput label="Duration" value="1m30s" onChange={onChange} />)
    expect(screen.getByText("= 1m30s")).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText("Duration"), "x")
    expect(onChange).toHaveBeenCalled()
  })

  it("hints when the value is unparseable", () => {
    render(<TimeDurationInput label="Duration" value="soon" onChange={vi.fn()} />)
    expect(screen.getByText(/Use a time like/)).toBeInTheDocument()
    expect(screen.getByLabelText("Duration")).toHaveAttribute("aria-invalid", "true")
  })

  it("shows an externally supplied error", () => {
    render(
      <TimeDurationInput label="Duration" value="30s" onChange={vi.fn()} error="Too long" />
    )
    expect(screen.getByText("Too long")).toBeInTheDocument()
  })
})

describe("RangeSelector", () => {
  it("renders start/end inputs and forwards edits to each bound", async () => {
    const onChange = vi.fn()
    render(
      <RangeSelector
        clipId="clip-1"
        durationMs={60000}
        start="10s"
        end="30s"
        onChange={onChange}
      />
    )
    const start = screen.getByLabelText("Start")
    const end = screen.getByLabelText("End")
    expect(start).toHaveValue("10s")
    expect(end).toHaveValue("30s")

    // Controlled input: one keystroke appends to the current prop value and
    // reports the whole [start, end] pair (the parent owns state).
    await userEvent.type(start, "5")
    expect(onChange).toHaveBeenLastCalledWith({ start: "10s5", end: "30s" })

    onChange.mockClear()
    await userEvent.type(end, "!")
    expect(onChange).toHaveBeenLastCalledWith({ start: "10s", end: "30s!" })
  })

  it("exposes draggable handles", () => {
    render(
      <RangeSelector clipId="c" durationMs={60000} start="0s" end="60s" onChange={vi.fn()} />
    )
    expect(screen.getByLabelText("Selection start")).toBeInTheDocument()
    expect(screen.getByLabelText("Selection end")).toBeInTheDocument()
  })
})

describe("EditModalShell", () => {
  function shell(state: Parameters<typeof EditModalShell>[0]["state"], extra = {}) {
    return render(
      <EditModalShell
        open
        onOpenChange={vi.fn()}
        title="Crop"
        description="Trim the clip"
        state={state}
        onSubmit={vi.fn()}
        canSubmit
        onRetry={vi.fn()}
        {...extra}
      >
        <div>form fields</div>
      </EditModalShell>
    )
  }

  it("renders the form and a credit hint while idle", () => {
    shell({ phase: "idle" }, { creditHint: "Uses 1 credit" })
    expect(screen.getByText("form fields")).toBeInTheDocument()
    expect(screen.getByText("Uses 1 credit")).toBeInTheDocument()
  })

  it("disables submit when canSubmit is false", () => {
    render(
      <EditModalShell
        open
        onOpenChange={vi.fn()}
        title="Crop"
        state={{ phase: "idle" }}
        onSubmit={vi.fn()}
        canSubmit={false}
        onRetry={vi.fn()}
      >
        <div>fields</div>
      </EditModalShell>
    )
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled()
  })

  it("calls onSubmit when the submit button is pressed", async () => {
    const onSubmit = vi.fn()
    shell({ phase: "idle" }, { onSubmit })
    await userEvent.click(screen.getByRole("button", { name: "Create" }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it("shows a spinner while working and hides the form", () => {
    shell({ phase: "polling", estimatedSeconds: 45 })
    expect(screen.getByRole("status")).toHaveTextContent("~45s")
    expect(screen.queryByText("form fields")).not.toBeInTheDocument()
  })

  it("shows an error with a retry action", async () => {
    const onRetry = vi.fn()
    shell({ phase: "error", message: "start before end" }, { onRetry })
    expect(screen.getByRole("alert")).toHaveTextContent("start before end")
    await userEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it("offers a View action on success", () => {
    shell({ phase: "success", clipIds: ["new-1"] })
    expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "View" })).toBeEnabled()
  })
})
