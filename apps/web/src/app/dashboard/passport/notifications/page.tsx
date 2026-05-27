import { NotificationCenterPanel } from "../../../../../components/passport/NotificationCenter"
import { PageHeader } from "../../../../../components/passport/shared"

export default function NotificationsPage() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 4px" }}>
      <PageHeader
        eyebrow="Notifications"
        title="Notification Center"
        description="Stay informed about access requests, verification updates, and passport activity."
      />
      <NotificationCenterPanel />
    </div>
  )
}
