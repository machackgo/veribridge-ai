import { redirect } from "next/navigation";

// Legacy student settings URL — the canonical Settings page now lives in the
// consolidated Student Dashboard. Redirect keeps old bookmarks/deep links
// working without ever rendering the legacy shell.
export default function Page() {
  redirect("/student/settings");
}
