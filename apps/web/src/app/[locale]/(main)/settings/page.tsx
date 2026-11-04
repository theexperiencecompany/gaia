import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
import { redirect } from "next/navigation";
import { DEFAULT_SECTION } from "@/features/settings/config/sectionKeys";

interface PageProps {
  searchParams: Promise<{ readonly section?: string }>;
}

export default async function SettingsPage({ searchParams }: PageProps) {
  const { section } = await searchParams;

  // Backward-compat: ?section=X redirects to /settings/X
  if (section) {
    redirect(`/settings/${section}`);
  }

  redirect(`/settings/${DEFAULT_SECTION}`);
}
