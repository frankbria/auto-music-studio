/**
 * Inline field-level validation error. Renders nothing when there's no message.
 * Pass `id` and reference it from the field's `aria-describedby` so a screen
 * reader associates the error with the input (not just the live-region announce).
 */
export function FieldError({
  id,
  message,
}: {
  id?: string
  message?: string | null
}) {
  if (!message) return null
  return (
    <p id={id} role="alert" className="text-sm text-destructive">
      {message}
    </p>
  )
}
