import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { VoiceLibrary } from "@/components/voices/VoiceLibrary"

export default function MePage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">Library</h1>

      <Tabs defaultValue="voices" className="mt-6">
        <TabsList>
          <TabsTrigger value="voices">Voices</TabsTrigger>
        </TabsList>

        <TabsContent value="voices" className="mt-4">
          <VoiceLibrary />
        </TabsContent>
      </Tabs>
    </div>
  )
}
