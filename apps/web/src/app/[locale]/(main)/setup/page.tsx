"use client";

import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

/**
 * First-run self-host setup wizard. The wizard itself fetches instance
 * setup status and redirects to /c when nothing needs configuring.
 */
export default function SetupPage() {
  return <SetupWizard />;
}
