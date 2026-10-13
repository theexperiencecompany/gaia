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
}

export function ComposioAuthConfigRow({
  row,
  value,
  onChange,
}: ComposioAuthConfigRowProps) {
  const isSetUp = row.auth_config_id !== null || value.trim() !== "";
  const inherited =
    row.source === "env" || row.source === "catalog"
      ? `${SOURCE_HINT[row.source]} (${row.auth_config_id})`
      : null;

  return (
    <SettingsRow
      label={row.name}
      description={inherited ?? `Toolkit: ${row.toolkit}`}
      icon={<IntegrationIcon integrationId={row.integration_id} size={24} />}
    >
      <div className="flex w-72 items-center gap-2">
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
