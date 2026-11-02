import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

const features = [
  {
    title: "Make a song from a sentence",
    description:
      "Describe a style and a mood, add lyrics if you have them, and get full tracks back in minutes.",
  },
  {
    title: "Shape it in the studio",
    description:
      "Extend, cover, repaint a section, add vocals or mash two songs together, then export stems for your DAW.",
  },
  {
    title: "Master it and release it",
    description:
      "Master your track, generate cover art, and publish to SoundCloud without leaving the app.",
  },
]

export default function HomePage() {
  return (
    <div className="flex min-h-full justify-center p-6">
      <div className="my-auto flex max-w-2xl flex-col gap-8">
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <HugeiconsIcon icon={MusicNote01Icon} size={22} />
            </span>
            <h1 className="text-2xl font-bold tracking-tight">
              Auto Music Studio
            </h1>
          </div>
          <p className="text-lg leading-relaxed text-muted-foreground">
            Write, produce and release original music with AI. Start from a
            prompt, refine every section, and take the finished song all the way
            to listeners.
          </p>
        </div>

        <ul className="grid gap-4 sm:grid-cols-3">
          {features.map((feature) => (
            <li key={feature.title} className="flex flex-col gap-1">
              <h2 className="font-semibold">{feature.title}</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {feature.description}
              </p>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap gap-3">
          <Button asChild size="lg">
            <Link href="/create">Get started</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/explore">Explore music</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
