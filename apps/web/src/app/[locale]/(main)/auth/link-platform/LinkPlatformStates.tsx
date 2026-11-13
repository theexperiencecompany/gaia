import { CheckmarkCircle02Icon } from "@icons";

import { LinkCard } from "./LinkCard";

/** No usable token/platform in the URL: there is nothing to link. */
export function InvalidLinkCard() {
  return (
    <LinkCard>
      <p className="text-zinc-400">
        Invalid or expired link. Request a new one from your bot with{" "}
        <span className="font-mono text-zinc-300">/auth</span>.
      </p>
    </LinkCard>
  );
}

interface LinkedSuccessCardProps {
  platformName: string;
}

/** The link landed: send the reader back to the platform they came from. */
export function LinkedSuccessCard({ platformName }: LinkedSuccessCardProps) {
  return (
    <LinkCard>
      <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-success/15">
        <CheckmarkCircle02Icon className="h-9 w-9 text-success" />
      </div>
      <h2 className="mb-2 text-xl font-semibold text-white">
        You&apos;re connected!
      </h2>
      <p className="text-sm text-zinc-400">
        Your {platformName} account is linked. Head back to {platformName} and
        say hi — GAIA&apos;s ready when you are.
      </p>
    </LinkCard>
  );
}
