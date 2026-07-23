import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react"
import { GlobeIcon, LinkIcon, LockIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import type { Visibility } from "@/lib/workspace-clips"

// US-20.7: read-only visibility indicator shown alongside a clip's other
// metadata badges (version, mode, style tags).

const CONFIG: Record<Visibility, { label: string; icon: IconSvgElement }> = {
  private: { label: "Private", icon: LockIcon },
  unlisted: { label: "Unlisted", icon: LinkIcon },
  public: { label: "Public", icon: GlobeIcon },
}

export type VisibilityBadgeProps = {
  visibility: Visibility
}

export function VisibilityBadge({ visibility }: VisibilityBadgeProps) {
  const { label, icon } = CONFIG[visibility]
  return (
    <Badge variant="outline" className="text-[10px]">
      <HugeiconsIcon icon={icon} size={12} />
      {label}
    </Badge>
  )
}
