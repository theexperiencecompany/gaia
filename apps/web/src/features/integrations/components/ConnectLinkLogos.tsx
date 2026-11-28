import { ArrowDataTransferHorizontalIcon } from "@icons";
import type { ConnectLinkPreviewResponse } from "@shared/api/generated";
import Image from "next/image";

import { IntegrationIcon } from "./IntegrationIcon";

interface ConnectLinkLogosProps {
  preview: Pick<ConnectLinkPreviewResponse, "integration_id" | "icon_url">;
}

const LOGO_SIZE = 40;

/** GAIA's logo and the integration's, side by side, for the connect-link page. */
export function ConnectLinkLogos({ preview }: ConnectLinkLogosProps) {
  return (
    <div className="mb-6 flex items-center justify-center gap-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-800">
        <Image
          src="/images/logos/logo.webp"
          alt="GAIA"
          width={LOGO_SIZE}
          height={LOGO_SIZE}
          priority
        />
      </div>
      <ArrowDataTransferHorizontalIcon className="h-5 w-5 text-zinc-500" />
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-800">
        <IntegrationIcon
          integrationId={preview.integration_id}
          iconUrl={preview.icon_url}
          size={LOGO_SIZE}
          loading="eager"
        />
      </div>
    </div>
  );
}
