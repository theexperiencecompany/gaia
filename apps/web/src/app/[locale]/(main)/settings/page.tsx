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
