import { notFound, redirect } from "next/navigation";
import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";
import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";
import { setupWizardOwed } from "@/features/setup-wizard/utils/setupWizardRoute";
import { isSelfhostWeb } from "@/lib/selfhost";

/**
 * First-run self-host setup wizard; hosted GAIA has none. Instances that owe
 * no wizard go straight to chat; the gate runs once on arrival, so a provider
 * saved mid-wizard (which settles needs_setup) does not cut the remaining
 * steps short.
 */
export default async function SetupPage() {
  if (!isSelfhostWeb()) notFound();
  if (!setupWizardOwed(await getSetupStatusServer())) redirect("/c");
  return <SetupWizard />;
}
