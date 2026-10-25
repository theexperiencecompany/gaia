import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import type { ComposioIntegrationSetup } from "@/features/settings/api/composioSetupApi";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";

const SOURCE_HINT: Record<"env" | "catalog", string> = {
  env: "Set in your .env",
  catalog: "Uses GAIA's default",
};

interface ComposioAuthConfigRowProps {
  row: ComposioIntegrationSetup;
  value: string;
  onChange: (value: string) => void;
  /** Opens the catalog on this toolkit, where GAIA creates the auth config; absent without a Composio key. */
  onSetUp?: (toolkit: string) => void;
}

export function ComposioAuthConfigRow({
  row,
  value,
  onChange,
  onSetUp,
}: ComposioAuthConfigRowProps) {
  const isSetUp = row.auth_config_id !== null || value.trim() !== "";
  const inherited =
    row.source === "env" || row.source === "catalog"
      ? `${SOURCE_HINT[row.source]} (${row.auth_config_id})`
      : null;

  return (
    <SettingsRow
      label={row.name}
      description={
        inherited ??
        (row.origin === "instance"
          ? "Added from the Composio catalog"
          : `Toolkit: ${row.toolkit}`)
      }
      icon={
        <IntegrationIcon
          integrationId={row.integration_id}
          iconUrl={row.icon_url}
          size={24}
        />
      }
    >
      <div className="flex w-96 items-center justify-end gap-2">
        {!isSetUp && onSetUp && (
          <Button
            size="sm"
            variant="flat"
            color="primary"
            className="shrink-0"
            onPress={() => onSetUp(row.toolkit.toLowerCase())}
          >
            Set up automatically
          </Button>
        )}
        {row.detected.length > 0 ? (
          <Select
            aria-label={`${row.name} auth config`}
            size="sm"
            placeholder="Pick an auth config"
            selectedKeys={value ? [value] : []}
            onSelectionChange={(keys) => {
              const [first] = Array.from(keys);
              onChange(first === undefined ? "" : String(first));
            }}
          >
            {row.detected.map((candidate) => (
              <SelectItem key={candidate.id} description={candidate.id}>
                {candidate.name}
              </SelectItem>
            ))}
          </Select>
        ) : (
          <Input
            aria-label={`${row.name} auth config id`}
            size="sm"
            placeholder="ac_..."
            value={value}
            onValueChange={onChange}
          />
        )}
        <Chip size="sm" variant="flat" color={isSetUp ? "success" : "default"}>
          {isSetUp ? "Set up" : "Not set up"}
        </Chip>
      </div>
    </SettingsRow>
  );
}
