import { redirect } from "next/navigation";

// The Today view now lives at the top of `/todos` — this route only redirects.
export default function DashboardPage() {
  redirect("/todos");
}
