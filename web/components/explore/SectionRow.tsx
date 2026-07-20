import type { ReactNode } from "react"

// Titled horizontal scroll row for an Explore section (US-20.1). A header slot
// carries the title plus optional controls (e.g. the trending range toggle),
// then children scroll horizontally with scroll-snap.
//
// ponytail: relies on native touch/trackpad horizontal scroll — no hover arrow
// buttons. Add them if pointer-only desktop users can't reach the overflow.

export function SectionRow({
  title,
  action,
  children,
}: {
  title: string
  /** Optional controls rendered at the end of the header row. */
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {action}
      </div>
      <div className="flex gap-3 overflow-x-auto scroll-smooth pb-2 [scroll-snap-type:x_mandatory] [&>*]:scroll-snap-align-start">
        {children}
      </div>
    </section>
  )
}
