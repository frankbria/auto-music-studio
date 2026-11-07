import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = { title: "Help · Auto Music Studio" }

// The in-app user guide (#342): the core workflows, each pointing at the screen where it happens.

const SECTIONS: { id: string; title: string; steps: React.ReactNode[] }[] = [
  {
    id: "create",
    title: "Make a song",
    steps: [
      <>
        Open <Link href="/create">Create</Link>. <strong>Simple</strong> takes a
        description of the song (and optional lyrics); <strong>Advanced</strong>{" "}
        adds style, lyrics, BPM, duration, key and more; <strong>Sounds</strong>{" "}
        makes one-shots and loops.
      </>,
      <>
        Pick a model at the top, then press Create. Progress shows below the
        form; new clips land in your Library.
      </>,
      <>
        Each creation spends credits. Your balance is in the sidebar, and{" "}
        <Link href="/settings/usage">Usage</Link> shows where they went. A
        failed creation refunds its credits.
      </>,
    ],
  },
  {
    id: "library",
    title: "Find, play and edit your songs",
    steps: [
      <>
        <Link href="/me">Library</Link> lists every clip in your workspaces.
        Search, filter, and press a clip&apos;s thumbnail to play it in the
        playbar at the bottom of every page.
      </>,
      <>
        Open a song to extend it, cover it in another style, repaint a section,
        remix it, or get the full song from a short clip. Edits make new clips
        and keep the original.
      </>,
      <>
        <Link href="/studio">Studio</Link> arranges clips on tracks, mixes them,
        and exports a mixdown or the stems for your DAW.
      </>,
    ],
  },
  {
    id: "share",
    title: "Share and release",
    steps: [
      <>
        A song is private until you make it public or unlisted from its card or
        page. Public songs appear in <Link href="/explore">Explore</Link>,{" "}
        <Link href="/feed">Feed</Link> and <Link href="/search">Search</Link>;
        Share copies a link to it.
      </>,
      <>
        <Link href="/playlists">Playlists</Link> collect songs, yours or
        anyone&apos;s public ones.
      </>,
      <>
        <Link href="/release">Mastering &amp; Distribution</Link> masters a
        song, prepares its release details and cover art, and uploads it to
        SoundCloud once you connect your account.
      </>,
    ],
  },
  {
    id: "account",
    title: "Your account and plan",
    steps: [
      <>
        <Link href="/settings">Account settings</Link> holds your profile and
        handle; <Link href="/settings/billing">Subscription</Link> changes plan.
        Pro adds more monthly credits and features such as mastering, stems and
        voice models; Enterprise adds 4K video and a priority queue.
      </>,
      <>
        <Link href="/notifications">Notifications</Link> tells you when long
        jobs finish and when a moderation decision affects your content. A
        decision can be appealed from the content&apos;s card.
      </>,
      <>
        <Link href="/labs">Labs</Link> lists experimental features you can
        switch on once they&apos;re available to your account.
      </>,
    ],
  },
]

export default function HelpPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 p-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Help</h1>
        <p className="text-muted-foreground">
          How to make, edit, share and release songs.
        </p>
        <nav aria-label="On this page">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {SECTIONS.map((section) => (
              <li key={section.id}>
                <a href={`#${section.id}`} className="underline">
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>
      {SECTIONS.map((section) => (
        <section
          key={section.id}
          id={section.id}
          aria-labelledby={`${section.id}-title`}
          className="flex flex-col gap-2"
        >
          <h2 id={`${section.id}-title`} className="text-lg font-medium">
            {section.title}
          </h2>
          <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm [&_a]:underline">
            {section.steps.map((step, index) => (
              <li key={index}>{step}</li>
            ))}
          </ol>
        </section>
      ))}
      <p className="text-sm text-muted-foreground">
        Still stuck?{" "}
        <Link href="/support" className="underline">
          Get help from the team
        </Link>
        . The API is documented at{" "}
        <Link href="/docs" prefetch={false} className="underline">
          /docs
        </Link>
        .
      </p>
    </div>
  )
}
