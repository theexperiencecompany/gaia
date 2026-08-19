"use client";

import { Button } from "@heroui/button";
import { MessageFavourite02Icon } from "@icons";
import { IntegrationsList } from "@/features/integrations/components/IntegrationsList";

interface IntegrationsPageBodyProps {
  onIntegrationClick: (id: string) => void;
  onRequestIntegration: () => void;
}

export function IntegrationsPageBody({
  onIntegrationClick,
  onRequestIntegration,
}: IntegrationsPageBodyProps) {
  return (
    <>
      <div className="absolute right-4 bottom-4 z-1">
        <Button
          color="primary"
          endContent={<MessageFavourite02Icon width={17} height={17} />}
          onPress={onRequestIntegration}
        >
          Request an Integration
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto pb-20">
        <div className="flex w-full justify-center px-5">
          <div className="w-full">
            <IntegrationsList onIntegrationClick={onIntegrationClick} />
          </div>
        </div>
      </div>
    </>
  );
}
