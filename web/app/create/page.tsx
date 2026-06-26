"use client"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useRequireAuth } from "@/hooks/use-require-auth"
import { SimpleCreationForm } from "@/components/create/SimpleCreationForm"

export default function CreatePage() {
  const { isLoading, isAuthenticated } = useRequireAuth()

  // ponytail: render nothing until authed — useRequireAuth redirects otherwise,
  // and this avoids flashing protected content during the check.
  if (isLoading || !isAuthenticated) return null

  return (
    <div className="p-8">
      <h1 className="mb-6 text-2xl font-semibold">Create</h1>
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
          <p className="text-sm text-muted-foreground">Coming soon.</p>
        </TabsContent>
        <TabsContent value="sounds">
          <p className="text-sm text-muted-foreground">Coming soon.</p>
        </TabsContent>
      </Tabs>
    </div>
  )
}
