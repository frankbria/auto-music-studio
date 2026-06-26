"use client"

import { useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  SidebarLeftIcon,
  UserIcon,
} from "@hugeicons/core-free-icons"

import { LAYOUT } from "@/lib/constants/layout"
import {
  bottomNav,
  mainNav,
  type NavDialogItem,
  type NavLinkItem,
} from "@/config/navigation"
import { useAuth } from "@/hooks/use-auth"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

/** Shared base styling for every interactive sidebar item (links, triggers). */
const sidebarItemBase =
  "flex h-10 items-center gap-3 rounded-md px-3 text-sidebar-foreground/70 outline-none transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-3 focus-visible:ring-ring/50"

/** Active when the path equals the route, or sits under it (root matches exactly). */
function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

function NavLink({
  item,
  expanded,
  active,
}: {
  item: NavLinkItem
  expanded: boolean
  active: boolean
}) {
  return (
    <Link
      href={item.href}
      // Collapsed items have no visible text, so the label must come from
      // aria-label; expanded, the visible span is the accessible name already.
      aria-label={expanded ? undefined : item.label}
      aria-current={active ? "page" : undefined}
      className={cn(
        sidebarItemBase,
        active && "bg-sidebar-accent text-sidebar-foreground",
        !expanded && "justify-center px-0"
      )}
    >
      <HugeiconsIcon icon={item.icon} size={22} className="shrink-0" />
      {expanded && <span className="truncate text-sm">{item.label}</span>}
    </Link>
  )
}

/**
 * Account menu body. Kept separate from the trigger so it (and its `useAuth`
 * call) only mounts when the dropdown opens — components rendering the Sidebar
 * without an AuthProvider stay unaffected unless they open this menu.
 */
function AccountMenuItems() {
  const { user, logout } = useAuth()
  return (
    <>
      <DropdownMenuLabel className="truncate">
        {user?.email ?? "Account"}
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem asChild>
        <Link href="/me">Profile</Link>
      </DropdownMenuItem>
      <DropdownMenuItem>Account settings</DropdownMenuItem>
      <DropdownMenuItem>Subscription</DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem variant="destructive" onSelect={() => logout()}>
        Log out
      </DropdownMenuItem>
    </>
  )
}

/** Profile avatar at the top; opens the account dropdown (spec section 1.4). */
function ProfileMenu({ expanded }: { expanded: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Open account menu"
        className={cn(sidebarItemBase, !expanded && "justify-center px-0")}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-sidebar-foreground">
          <HugeiconsIcon icon={UserIcon} size={18} />
        </span>
        {expanded && <span className="truncate text-sm">Your account</span>}
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="start" className="w-48">
        <AccountMenuItems />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Bottom-pinned dialog item (Account): opens a placeholder dialog (spec 1.2). */
function NavDialog({
  item,
  expanded,
}: {
  item: NavDialogItem
  expanded: boolean
}) {
  return (
    <Dialog>
      <DialogTrigger
        aria-label={expanded ? undefined : item.label}
        className={cn(sidebarItemBase, !expanded && "justify-center px-0")}
      >
        <HugeiconsIcon icon={item.icon} size={22} className="shrink-0" />
        {expanded && <span className="truncate text-sm">{item.label}</span>}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{item.label}</DialogTitle>
          <DialogDescription>
            Account, subscription, and billing details arrive in a later story.
          </DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Primary sidebar navigation (US-15.3). Collapsed 64px icon bar by default;
 * the toggle expands it to an icon+label rail. Lives in the persistent App
 * Router layout, so the expand state survives route changes.
 */
export function Sidebar() {
  const pathname = usePathname()
  const [expanded, setExpanded] = useState(false)

  return (
    <aside
      data-testid="app-sidebar"
      aria-label="Primary navigation"
      style={{
        width: expanded ? LAYOUT.sidebarExpandedWidth : LAYOUT.sidebarWidth,
      }}
      className="z-40 flex h-full shrink-0 flex-col gap-2 overflow-hidden border-r border-border bg-sidebar px-2 py-4 transition-all duration-200"
    >
      <button
        type="button"
        aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className={cn(sidebarItemBase, !expanded && "justify-center px-0")}
      >
        <HugeiconsIcon
          icon={SidebarLeftIcon}
          size={22}
          className={cn("shrink-0 transition-transform", !expanded && "rotate-180")}
        />
        {expanded && <span className="truncate text-sm">Collapse</span>}
      </button>

      <ProfileMenu expanded={expanded} />

      <nav aria-label="Main" className="flex flex-1 flex-col gap-1">
        {mainNav.map((item) => (
          <NavLink
            key={item.id}
            item={item}
            expanded={expanded}
            active={isActive(pathname, item.href)}
          />
        ))}
      </nav>

      <div className="flex flex-col gap-1">
        {bottomNav.map((item) =>
          item.isDialog ? (
            <NavDialog key={item.id} item={item} expanded={expanded} />
          ) : (
            <NavLink
              key={item.id}
              item={item}
              expanded={expanded}
              active={isActive(pathname, item.href)}
            />
          )
        )}
      </div>
    </aside>
  )
}
