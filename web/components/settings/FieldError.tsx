/** Inline field-level validation error. Renders nothing when there's no message. */
export function FieldError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  )
}
