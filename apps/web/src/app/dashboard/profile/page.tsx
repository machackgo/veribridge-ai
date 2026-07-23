import { redirect } from "next/navigation";

// Legacy student profile URL — the canonical Account page now lives in the
// consolidated Student Dashboard. Permanent client-visible redirect keeps old
// bookmarks/deep links working without ever rendering the legacy shell.
export default function Page() {
  redirect("/student/account");
}
