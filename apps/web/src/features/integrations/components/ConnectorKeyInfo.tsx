import { Chip, Link } from "@heroui/react";
import { SquareArrowUpRight02Icon, SquareLock02Icon } from "@icons";
import type { ConnectorCardInfo } from "@shared/api/generated";

interface ConnectorKeyInfoProps {
  connector: ConnectorCardInfo;
}

/** Every host a connector's key can reach, and where the user creates that key. */
export function ConnectorKeyInfo({ connector }: ConnectorKeyInfoProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1 text-xs text-zinc-400">
          <SquareLock02Icon className="size-3.5" />
          Your key goes only to:
        </span>
        <div className="flex flex-wrap gap-1.5">
          {connector.allowedHosts.map((host) => (
            <Chip key={host} size="sm" variant="soft">
              {host}
            </Chip>
          ))}
        </div>
      </div>
      {connector.tokenUrl && (
        <Link
          href={connector.tokenUrl}
          target="_blank"
          rel="noreferrer"
          className="flex w-fit items-center text-xs text-primary"
        >
          Get your {connector.keyLabel}
          <SquareArrowUpRight02Icon className="ml-1 size-3.5" />
        </Link>
      )}
    </div>
  );
}
