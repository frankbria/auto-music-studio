import { NotificationsView } from "@/components/notifications/NotificationsView"

// Notifications route /notifications (US-20.6). State comes from the root
// NotificationsProvider (app/layout), shared with the sidebar bell badge.
export default function NotificationsPage() {
  return <NotificationsView />
}
