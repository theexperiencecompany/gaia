import { redirect } from "next/navigation";
import { getSetupStatusServer } from "@/features/auth/api/serverSetupStatusApi";
import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

// The gate reads live instance state (setup/status), so it can never prerender.
export const dynamic = "force-dynamic";

/**
 * First-run self-host setup wizard. Instances that owe no setup go straight
 * to chat; the gate runs once on arrival, so a provider saved mid-wizard
 * (which settles needs_setup) does not cut the remaining steps short.
 */
export default async function SetupPage() {
  const setupStatus = await getSetupStatusServer();
  if (setupStatus && !setupStatus.needs_setup) redirect("/c");
  return <SetupWizard />;
}
