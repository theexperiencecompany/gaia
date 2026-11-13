import { Button } from "@heroui/button";
import { ArrowDown01Icon, CheckmarkCircle02Icon } from "@icons";
import type { ProviderCatalog } from "@/features/settings/api/providersApi";
import { featureEngineLabel } from "@/features/settings/utils/providerCatalog";
import { cn } from "@/lib/utils";
import type { FeatureGroup } from "./providerRows";

/** The free built-in already serving the feature, with the optional upgrade behind a disclosure. */
export function BuiltInWorking({
  group,
  isOpen,
  onToggle,
}: {
  group: FeatureGroup;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const builtIn = group.spec.built_in;
  if (!builtIn) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 items-start gap-2">
        <CheckmarkCircle02Icon
          size={18}
          className="mt-0.5 shrink-0 text-emerald-400"
        />
        <div className="min-w-0">
          <p className="text-sm text-zinc-100">
            Already working with {builtIn.label}
          </p>
          <p className="mt-0.5 text-xs text-zinc-500">{builtIn.description}</p>
        </div>
      </div>
      {group.rows.length > 0 && (
        <Button
          size="sm"
          variant="flat"
          aria-expanded={isOpen}
          endContent={
            <ArrowDown01Icon
              size={16}
              className={cn("transition-transform", isOpen && "rotate-180")}
            />
          }
          onPress={onToggle}
        >
          Use a better provider
        </Button>
      )}
    </div>
  );
}

/** What the feature runs on now: the serving engine and its backups, or the free built-in. */
export function EngineLine({
  group,
  catalog,
}: {
  group: FeatureGroup;
  catalog: ProviderCatalog;
}) {
  const { spec } = group;
  const [primary, ...backups] = (group.status?.in_use ?? []).map((engine) =>
    featureEngineLabel(engine, spec, catalog),
  );
  const builtIn = spec.built_in;

  const detail = (): string | undefined => {
    if (!primary) return "Pick a provider below to turn it on.";
    if (backups.length > 0) return `Backup: ${backups.join(", ")}`;
    return primary === builtIn?.label ? builtIn.description : undefined;
  };

  return (
    <div>
      <p className="text-sm text-zinc-100">
        {primary ? `Using: ${primary}` : "Not set up yet"}
      </p>
      {detail() && <p className="mt-0.5 text-xs text-zinc-500">{detail()}</p>}
    </div>
  );
}
