"use client"

import { useMemo, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Cancel01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { FieldError } from "@/components/settings/FieldError"
import {
  STYLE_SUGGESTIONS,
  STYLE_TAGS_MAX_ITEMS,
  validateNewStyleTag,
} from "@/lib/profile"

/**
 * Editable list of style tags shown as removable pill badges, with a typeahead
 * over a static suggestion list. Validation mirrors the backend (max count,
 * length, no duplicates/empties); the parent owns the tags array.
 */
export function StyleTagsInput({
  tags,
  onChange,
}: {
  tags: string[]
  onChange: (next: string[]) => void
}) {
  const [draft, setDraft] = useState("")
  const [error, setError] = useState<string | null>(null)
  // Highlighted option for keyboard navigation (-1 = none); `dismissed` closes
  // the list on Escape until the next keystroke reopens it.
  const [activeIndex, setActiveIndex] = useState(-1)
  const [dismissed, setDismissed] = useState(false)

  const suggestions = useMemo(() => {
    const q = draft.trim().toLowerCase()
    if (q.length === 0) return []
    const taken = new Set(tags.map((t) => t.toLowerCase()))
    return STYLE_SUGGESTIONS.filter(
      (s) => s.includes(q) && !taken.has(s)
    ).slice(0, 6)
  }, [draft, tags])

  function add(raw: string) {
    // Normalize to lowercase so custom tags match the (lowercase) suggestions
    // and the case-insensitive duplicate guard, keeping the list consistent.
    const tag = raw.trim().toLowerCase()
    const err = validateNewStyleTag(tag, tags)
    if (err) {
      setError(err)
      return
    }
    onChange([...tags, tag])
    setDraft("")
    setError(null)
  }

  function remove(tag: string) {
    onChange(tags.filter((t) => t !== tag))
    setError(null)
  }

  const draftKey = draft.trim().toLowerCase()
  const showAddCustom =
    draftKey.length > 0 &&
    !suggestions.some((s) => s === draftKey) &&
    !tags.some((t) => t.toLowerCase() === draftKey)

  // Unified, ordered options so keyboard navigation has a single index space.
  const options = [
    ...suggestions.map((s) => ({ id: `style-opt-${s}`, label: s, value: s })),
    ...(showAddCustom
      ? [{ id: "style-opt-add", label: `Add "${draft.trim()}"`, value: draft }]
      : []),
  ]
  const listOpen = options.length > 0 && !dismissed
  const activeId =
    listOpen && activeIndex >= 0 ? options[activeIndex]?.id : undefined

  function resetList() {
    setActiveIndex(-1)
    setDismissed(false)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault()
      add(activeIndex >= 0 ? (options[activeIndex]?.value ?? draft) : draft)
      return
    }
    if (e.key === "Escape" && listOpen) {
      setDismissed(true)
      setActiveIndex(-1)
      return
    }
    if (!listOpen) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setActiveIndex((i) => (i + 1) % options.length)
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActiveIndex((i) => (i <= 0 ? options.length - 1 : i - 1))
    }
  }

  return (
    <div data-slot="style-tags" className="flex flex-col gap-2">
      {tags.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Style tags">
          {tags.map((tag) => (
            <li key={tag}>
              <Badge variant="secondary" className="gap-1 pr-1">
                {tag}
                <button
                  type="button"
                  aria-label={`Remove ${tag}`}
                  onClick={() => remove(tag)}
                  className="rounded-sm opacity-70 transition-opacity hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
                >
                  <HugeiconsIcon icon={Cancel01Icon} size={12} />
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      )}

      <div className="relative">
        <Input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            setError(null)
            resetList()
          }}
          onKeyDown={onKeyDown}
          placeholder="Add a style (e.g. cello, lo-fi)"
          aria-label="Add a style tag"
          role="combobox"
          aria-expanded={listOpen}
          aria-controls="style-suggestions-list"
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          disabled={tags.length >= STYLE_TAGS_MAX_ITEMS}
        />
        {listOpen && (
          <ul
            id="style-suggestions-list"
            role="listbox"
            aria-label="Style suggestions"
            className="absolute z-10 mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover py-1 shadow-md"
          >
            {options.map((opt, i) => (
              <li key={opt.id}>
                <button
                  type="button"
                  id={opt.id}
                  role="option"
                  aria-selected={i === activeIndex}
                  onClick={() => add(opt.value)}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={
                    "flex w-full px-2.5 py-1.5 text-left text-sm hover:bg-muted" +
                    (i === activeIndex ? " bg-muted" : "")
                  }
                >
                  {opt.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <FieldError message={error} />
    </div>
  )
}
