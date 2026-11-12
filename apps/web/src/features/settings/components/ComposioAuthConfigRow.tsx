import { Button, Chip, Input, ListBox, Select, TextField } from "@heroui/react";
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
            variant="tertiary"
            className="shrink-0"
            onPress={() => onSetUp(row.toolkit.toLowerCase())}
          >
            Set up automatically
          </Button>
        )}
        {row.detected.length > 0 ? (
          <Select
            aria-label={`${row.name} auth config`}
            placeholder="Pick an auth config"
            selectedKey={value || null}
            onSelectionChange={(key) => {
              onChange(key === null ? "" : String(key));
            }}
          >
            <Select.Trigger>
              <Select.Value />
              <Select.Indicator />
            </Select.Trigger>
            <Select.Popover>
              <ListBox>
                {row.detected.map((candidate) => (
                  <ListBox.Item
                    key={candidate.id}
                    id={candidate.id}
                    textValue={candidate.name}
                  >
                    <span className="flex flex-col items-start">
                      <span>{candidate.name}</span>
                      <span className="text-xs text-zinc-500">
                        {candidate.id}
                      </span>
                    </span>
                  </ListBox.Item>
                ))}
              </ListBox>
            </Select.Popover>
          </Select>
        ) : (
          <TextField
            aria-label={`${row.name} auth config id`}
            value={value}
            onChange={onChange}
          >
            <Input placeholder="ac_..." />
          </TextField>
        )}
        <Chip size="sm" variant="soft" color={isSetUp ? "success" : "default"}>
          {isSetUp ? "Set up" : "Not set up"}
        </Chip>
      </div>
    </SettingsRow>
  );
}
