import { ArrowDataTransferHorizontalIcon, ConnectIcon } from "@icons";
import Image from "next/image";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";

interface ConnectLinkLogosProps {
  integrationId: string;
  iconUrl: string | null;
}

const LOGO_SIZE = 40;

/** GAIA's logo and the integration's, side by side, for the connect-link page. */
export function ConnectLinkLogos({
  integrationId,
  iconUrl,
}: ConnectLinkLogosProps) {
  const integrationIcon = getToolCategoryIcon(
    integrationId,
    {
      size: LOGO_SIZE,
      width: LOGO_SIZE,
      height: LOGO_SIZE,
      showBackground: false,
      loading: "eager",
    },
    iconUrl,
  ) ?? <ConnectIcon className="h-10 w-10 text-accent" />;

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
        {integrationIcon}
      </div>
    </div>
  );
}
