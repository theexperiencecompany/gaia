import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";

/** Stands in for Connect on an integration this instance has no Composio auth config for. */
export function InstanceSetupNotice() {
  return (
    <Tooltip content="An admin can add it in Settings > Integrations setup.">
      <Chip size="sm" variant="flat" color="default">
        Not set up on this instance
      </Chip>
    </Tooltip>
  );
}
