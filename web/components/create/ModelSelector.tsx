"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, LockIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useModelSelection } from "@/contexts/model-selection-context"
import { groupByCategory } from "@/lib/models"

/**
 * Model/version selector (US-16.4). A badge-style dropdown showing the current
 * model, with options grouped by category. Pro-only models display a Pro badge
 * and a lock icon for free-tier users (display only — selection is not yet
 * tier-enforced on the backend). Rendered once above the creation tabs so the
 * choice persists as the user switches between Simple, Advanced, and Sounds.
 */
export function ModelSelector() {
  const { models, selectedModel, setSelectedModel, subscriptionTier } =
    useModelSelection()
  const isFreeTier = subscriptionTier !== "pro"

  const current = models.find((m) => m.key === selectedModel)
  const triggerLabel = current?.display_name ?? "Select model"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="Select model"
          data-testid="model-selector-trigger"
        >
          {triggerLabel}
          <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {models.length === 0 ? (
          <DropdownMenuItem disabled>No models available</DropdownMenuItem>
        ) : (
          groupByCategory(models).map(([category, group], groupIndex) => (
            <div key={category}>
              {groupIndex > 0 && <DropdownMenuSeparator />}
              <DropdownMenuLabel>{category}</DropdownMenuLabel>
              {group.map((model) => {
                const locked = model.pro_only && isFreeTier
                return (
                  <DropdownMenuItem
                    key={model.key}
                    onSelect={() => setSelectedModel(model.key)}
                    className="flex flex-col items-start gap-0.5"
                    data-testid={`model-option-${model.key}`}
                    data-selected={model.key === selectedModel}
                  >
                    <div className="flex w-full items-center gap-2">
                      <span className="font-medium">{model.display_name}</span>
                      {model.pro_only && (
                        <Badge variant="secondary" className="ml-auto">
                          {locked && (
                            <HugeiconsIcon
                              icon={LockIcon}
                              data-icon="inline-start"
                            />
                          )}
                          Pro
                        </Badge>
                      )}
                    </div>
                    <span className="line-clamp-1 text-xs text-muted-foreground">
                      {model.description}
                    </span>
                  </DropdownMenuItem>
                )
              })}
            </div>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
