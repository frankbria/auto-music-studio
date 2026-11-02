import type { IconSvgElement } from "@hugeicons/react"
import {
  Compass01Icon,
  HomeIcon,
  LibraryIcon,
  MixerIcon,
  MusicNote01Icon,
  Notification01Icon,
  Playlist01Icon,
  Search01Icon,
  TestTube01Icon,
  TradeUpIcon,
  Upload01Icon,
  UserCircleIcon,
} from "@hugeicons/core-free-icons"

/** A sidebar destination: single source of truth for routes + icons (US-15.3, spec section 1.2). */
export type NavLinkItem = {
  id: string
  label: string
  href: string
  icon: IconSvgElement
}

export const mainNav: NavLinkItem[] = [
  { id: "home", label: "Home", href: "/", icon: HomeIcon },
  { id: "explore", label: "Explore", href: "/explore", icon: Compass01Icon },
  { id: "create", label: "Create", href: "/create", icon: MusicNote01Icon },
  { id: "studio", label: "Studio", href: "/studio", icon: MixerIcon },
  { id: "library", label: "Library", href: "/me", icon: LibraryIcon },
  {
    id: "playlists",
    label: "Playlists",
    href: "/playlists",
    icon: Playlist01Icon,
  },
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

export const bottomNav: NavLinkItem[] = [
  { id: "labs", label: "Labs", href: "/labs", icon: TestTube01Icon },
  { id: "account", label: "Account", href: "/settings", icon: UserCircleIcon },
]
