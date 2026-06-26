import type { IconSvgElement } from "@hugeicons/react"
import {
  Compass01Icon,
  HomeIcon,
  LibraryIcon,
  MixerIcon,
  MusicNote01Icon,
  Notification01Icon,
  Search01Icon,
  TestTube01Icon,
  TradeUpIcon,
  Upload01Icon,
  UserCircleIcon,
} from "@hugeicons/core-free-icons"

/**
 * A sidebar destination. Most route via `href` (`link`); `Account` opens a
 * dialog (`dialog`) and so carries no route. The discriminated union keeps the
 * two kinds from borrowing each other's fields. Single source of truth for
 * routes + icons (US-15.3, spec section 1.2).
 */
type NavItemBase = { id: string; label: string; icon: IconSvgElement }
export type NavLinkItem = NavItemBase & { href: string; isDialog?: false }
export type NavDialogItem = NavItemBase & { isDialog: true }
export type NavItem = NavLinkItem | NavDialogItem

export const mainNav: NavLinkItem[] = [
  { id: "home", label: "Home", href: "/", icon: HomeIcon },
  { id: "explore", label: "Explore", href: "/explore", icon: Compass01Icon },
  { id: "create", label: "Create", href: "/create", icon: MusicNote01Icon },
  { id: "studio", label: "Studio", href: "/studio", icon: MixerIcon },
  { id: "library", label: "Library", href: "/me", icon: LibraryIcon },
  { id: "search", label: "Search", href: "/search", icon: Search01Icon },
  { id: "feed", label: "Feed", href: "/feed", icon: TradeUpIcon },
  {
    id: "notifications",
    label: "Notifications",
    href: "/notifications",
    icon: Notification01Icon,
  },
  {
    id: "release",
    label: "Mastering & Distribution",
    href: "/release",
    icon: Upload01Icon,
  },
]

export const bottomNav: NavItem[] = [
  { id: "labs", label: "Labs", href: "/labs", icon: TestTube01Icon },
  { id: "account", label: "Account", icon: UserCircleIcon, isDialog: true },
]
