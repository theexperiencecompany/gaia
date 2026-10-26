import { Avatar } from "@heroui/avatar";
import {
  CheckmarkBadge01Icon,
  DateTimeIcon,
  GitForkIcon,
  LayersIcon,
  UserCircle02Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import Image from "next/image";
import type { ReactNode } from "react";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

interface IntegrationMetaBarProps {
  integration: PublicIntegrationResponse;
  isNative: boolean;
}

const AUTH_TYPE_LABELS: Record<"oauth" | "bearer", string> = {
  oauth: "OAuth",
  bearer: "API Key",
};

function MetaCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-zinc-900/50 backdrop-blur-md px-4 py-3">
      {children}
    </div>
  );
}

function CategoryCard({ category }: { category: string }) {
  return (
    <MetaCard>
      <LayersIcon width={24} height={24} className="text-zinc-400" />
      <div>
        <div className="text-xs text-zinc-500">Category</div>
        <div className="text-sm text-zinc-300">
          {category.charAt(0).toUpperCase() + category.slice(1)}
        </div>
      </div>
    </MetaCard>
  );
}

function NativeCreatorCard() {
  return (
    <MetaCard>
      <div className="flex h-8 w-8 items-center justify-center overflow-hidden">
        <Image
          src="/brand/gaia_logo.svg"
          alt="GAIA"
          width={100}
          height={100}
          className="object-contain"
        />
      </div>
      <div>
        <div className="text-xs text-zinc-500">Created by</div>
        <div className="flex items-center gap-1 text-sm text-zinc-300">
          GAIA Team
          <CheckmarkBadge01Icon
            width={15}
            height={15}
            className="text-primary"
          />
        </div>
      </div>
    </MetaCard>
  );
}

function CommunityCreatorCard({
  creator,
}: {
  creator: PublicIntegrationResponse["creator"];
}) {
  return (
    <MetaCard>
      {creator?.picture ? (
        <Avatar
          src={creator.picture || undefined}
          name={creator.name || undefined}
          size="sm"
          className="h-6 w-6"
          imgProps={{ width: 24, height: 24 }}
        />
      ) : (
        <UserCircle02Icon width={24} height={24} className="text-zinc-400" />
      )}
      <div>
        <div className="text-xs text-zinc-500">Created by</div>
        <div className="text-sm text-zinc-300">
          {creator?.name || "Unknown"}
        </div>
      </div>
    </MetaCard>
  );
}

function UsersCard({
  cloneCount,
}: Pick<PublicIntegrationResponse, "cloneCount">) {
  return (
    <MetaCard>
      <GitForkIcon width={24} height={24} className="text-zinc-400" />
      <div>
        <div className="text-xs text-zinc-500">Users</div>
        <div className="text-sm text-zinc-300">{cloneCount}</div>
      </div>
    </MetaCard>
  );
}

function AuthCard({ authType }: Pick<PublicIntegrationResponse, "authType">) {
  return (
    <MetaCard>
      <LayersIcon width={24} height={24} className="text-zinc-400" />
      <div>
        <div className="text-xs text-zinc-500">Auth</div>
        <div className="text-sm text-zinc-300">
          {authType === "oauth" || authType === "bearer"
            ? AUTH_TYPE_LABELS[authType]
            : "No Auth"}
        </div>
      </div>
    </MetaCard>
  );
}

function PublishedCard({
  publishedAt,
}: Pick<PublicIntegrationResponse, "publishedAt">) {
  return (
    <MetaCard>
      <DateTimeIcon width={24} height={24} className="text-zinc-400" />
      <div>
        <div className="text-xs text-zinc-500">Published</div>
        <div className="text-sm text-zinc-300">
          {publishedAt
            ? formatDistanceToNow(new Date(publishedAt), { addSuffix: true })
            : "N/A"}
        </div>
      </div>
    </MetaCard>
  );
}

export function IntegrationMetaBar({
  integration,
  isNative,
}: IntegrationMetaBarProps) {
  return (
    <div className="flex flex-wrap items-start gap-4">
      <CategoryCard category={integration.category} />
      {isNative ? (
        <NativeCreatorCard />
      ) : (
        <CommunityCreatorCard creator={integration.creator} />
      )}
      {!isNative && <UsersCard cloneCount={integration.cloneCount} />}
      {isNative ? (
        <AuthCard authType={integration.authType} />
      ) : (
        <PublishedCard publishedAt={integration.publishedAt} />
      )}
    </div>
  );
}
