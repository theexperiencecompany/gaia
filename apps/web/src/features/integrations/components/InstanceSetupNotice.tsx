"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import Link from "next/link";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { COMPOSIO_SETUP_PATH } from "@/features/settings/api/composioSetupApi";

const ASK_ADMIN = "Ask this instance's admin to set it up.";

/** Stands in for Connect on an integration this instance has no Composio auth config for; the admin gets the fix. */
export function InstanceSetupNotice() {
  const { role } = useCurrentUser();
  if (role === "admin") {
    return (
      <Tooltip content="Not set up on this instance yet">
        <Button
          as={Link}
          href={COMPOSIO_SETUP_PATH}
          size="sm"
          variant="flat"
          color="warning"
          className="shrink-0 text-xs"
        >
          Set up
        </Button>
      </Tooltip>
    );
  }
  return (
    <Tooltip content={ASK_ADMIN}>
      <Chip size="sm" variant="flat">
        Not set up here
      </Chip>
    </Tooltip>
  );
}

/** The integration panel's version: why Connect is missing, and the fix, in place of a toast. */
export function InstanceSetupCallout({ name }: { name: string }) {
  const { role } = useCurrentUser();
  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-zinc-800 p-4">
      <div>
        <p className="text-sm font-medium text-zinc-100">
          {name} isn&apos;t set up on this instance
        </p>
        <p className="mt-1 text-xs text-zinc-400">
          {role === "admin"
            ? "Enable it in Integrations setup, then anyone here can connect it."
            : ASK_ADMIN}
        </p>
      </div>
      {role === "admin" && (
        <Button
          as={Link}
          href={COMPOSIO_SETUP_PATH}
          size="sm"
          color="primary"
          className="self-start"
        >
          Set it up
        </Button>
      )}
    </div>
  );
}
