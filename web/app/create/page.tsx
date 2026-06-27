"use client"

import { useRouter } from "next/navigation"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useRequireAuth } from "@/hooks/use-require-auth"
import { SimpleCreationForm } from "@/components/create/SimpleCreationForm"
import { AdvancedCreationForm } from "@/components/create/AdvancedCreationForm"
import { SoundsCreationForm } from "@/components/create/SoundsCreationForm"
import { ModelSelector } from "@/components/create/ModelSelector"
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel"
import { ModelSelectionProvider } from "@/contexts/model-selection-context"

export default function CreatePage() {
  const { isLoading, isAuthenticated } = useRequireAuth()
  const router = useRouter()

  // ponytail: render nothing until authed — useRequireAuth redirects otherwise,
  // and this avoids flashing protected content during the check.
  if (isLoading || !isAuthenticated) return null

  return (
    // The provider wraps the tabs so the selected model persists across tab
    // switches (US-16.4); the selector sits in the header, outside the Tabs.
    <ModelSelectionProvider>
      <div className="flex h-full">
        <div className="min-w-0 flex-1 overflow-y-auto p-8">
          <div className="mb-6 flex items-center justify-between gap-4">
            <h1 className="text-2xl font-semibold">Create</h1>
            <ModelSelector />
          </div>
          <Tabs defaultValue="simple">
            <TabsList>
              <TabsTrigger value="simple">Simple</TabsTrigger>
              <TabsTrigger value="advanced">Advanced</TabsTrigger>
              <TabsTrigger value="sounds">Sounds</TabsTrigger>
            </TabsList>
            <TabsContent value="simple">
              <SimpleCreationForm />
            </TabsContent>
            <TabsContent value="advanced">
              <AdvancedCreationForm />
            </TabsContent>
            <TabsContent value="sounds">
              <SoundsCreationForm />
            </TabsContent>
          </Tabs>
        </div>
        {/* Clip library (US-16.5). Hidden below lg to keep the form usable at
            the minimum supported width, mirroring the app shell's RightPanel. */}
        <aside
          aria-label="Clip library"
          className="hidden w-80 shrink-0 flex-col border-l border-border p-4 lg:flex"
        >
          <WorkspacePanel onNavigateWorkspaces={() => router.push("/studio")} />
        </aside>
      </div>
    </ModelSelectionProvider>
  )
}
