import { Button } from "@heroui/button";
import { PuzzleIcon } from "@icons";
import { useRouter } from "next/navigation";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import type { ConnectOptionsData } from "@/features/integrations/types";

interface ConnectOptionsProps {
  connect_options: ConnectOptionsData;
}

/**
 * The seeded Getting-started thread's connect row: plain buttons under the
 * routines bubble, no card chrome. Same tab, because a button inside the app
 * navigates; the integrations page opens the connect flow on arrival when the
 * path carries `?connect=<id>`.
 */
export default function ConnectOptions({
  connect_options,
}: ConnectOptionsProps) {
  const router = useRouter();
  const { getIntegrationIconUrl } = useIntegrationLookup();
  if (!connect_options?.options?.length) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {connect_options.options.map((option) => (
        <Button
          key={option.href}
          size="sm"
          variant="flat"
          startContent={
            option.integration_id ? (
              <IntegrationIcon
                integrationId={option.integration_id}
                iconUrl={getIntegrationIconUrl(option.integration_id)}
                size={16}
              />
            ) : (
              <PuzzleIcon className="size-4 shrink-0" />
            )
          }
          onPress={() => router.push(option.href)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
