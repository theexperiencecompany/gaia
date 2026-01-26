"use client";

import { PromoBanner } from "@/components/shared/PromoBanner";
import { ArrowRight02Icon, UserGroupIcon, ZapIcon } from "@/icons";

interface CommunityBannerProps {
  onCreateWorkflow?: () => void;
}

export function CommunityBanner({ onCreateWorkflow }: CommunityBannerProps) {
  return (
    <PromoBanner
      icon={<UserGroupIcon className="h-6 w-6 text-primary" />}
      title="Explore the Community"
      description="Discover community workflows or publish your own for others to use."
      secondaryAction={{
        label: "Browse Use Cases",
        icon: <ArrowRight02Icon className="h-4 w-4" />,
        href: "/use-cases",
      }}
      primaryAction={{
        label: "Create New Workflow",
        icon: <ZapIcon className="h-4 w-4" />,
        onPress: onCreateWorkflow,
      }}
    />
  );
}
