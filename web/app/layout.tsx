import type { Metadata } from "next"
import { Nunito_Sans } from "next/font/google"

import "./globals.css"
import { AppShell, BottomPlaybar } from "@/components/layout"
import { ThemeProvider } from "@/components/theme-provider"
import { AuthProvider } from "@/contexts/auth-context"
import { NotificationsProvider } from "@/contexts/notifications-context"
import { PlayerProvider } from "@/contexts/player-context"
import { VideoJobsProvider } from "@/contexts/video-jobs-context"
import { cn } from "@/lib/utils"

export const metadata: Metadata = {
  title: "Auto Music Studio",
  description: "AI-powered music creation studio",
}

const nunitoSans = Nunito_Sans({ subsets: ["latin"], variable: "--font-sans" })

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn("antialiased", nunitoSans.variable)}
    >
      <body>
        <ThemeProvider>
          <AuthProvider>
            <NotificationsProvider>
              {/* Watches in-flight video renders across navigation so completion
                  notifies globally (US-22.3). Inside Notifications (needs notify)
                  and Auth (needs the token). */}
              <VideoJobsProvider>
                <PlayerProvider>
                  <AppShell>{children}</AppShell>
                  {/* Sibling of AppShell so the fixed playbar stays viewport-anchored. */}
                  <BottomPlaybar />
                </PlayerProvider>
              </VideoJobsProvider>
            </NotificationsProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
