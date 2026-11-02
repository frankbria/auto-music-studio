// Where a user goes for help (#339). Read at request time on the server, so one image serves every deployment.

export type SupportContact = { href: string; label: string } | null

/** An email address becomes a mailto: link, a URL a plain link; anything else (or nothing) is no link. */
export function supportContact(
  value: string | undefined = process.env.SUPPORT_CONTACT
): SupportContact {
  const contact = value?.trim()
  if (!contact) return null
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact)) {
    return { href: `mailto:${contact}`, label: contact }
  }
  if (/^https?:\/\//.test(contact)) return { href: contact, label: contact }
  return null
}
