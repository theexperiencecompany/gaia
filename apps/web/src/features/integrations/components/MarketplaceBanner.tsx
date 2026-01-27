"use client";

import { PromoBanner } from "@/components/shared/PromoBanner";
import {
  ArrowRight02Icon,
  CursorAddSelectionIcon,
  PackageOpenIcon,
} from "@/icons";

interface MarketplaceBannerProps {
  onCreateCustomIntegration?: () => void;
}

export function MarketplaceBanner({
  onCreateCustomIntegration,
}: MarketplaceBannerProps) {
  return (
    <PromoBanner
      icon={<PackageOpenIcon className="h-6 w-6 text-primary" />}
      title="Explore the Marketplace"
      description="Discover community integrations or publish your own for others to use."
      secondaryAction={{
        label: "Create Custom Integration",
        icon: <CursorAddSelectionIcon className="h-4 w-4" />,
        onPress: onCreateCustomIntegration,
      }}
      primaryAction={{
        label: "Browse Marketplace",
        icon: <ArrowRight02Icon className="h-4 w-4" />,
        href: "/marketplace",
      }}
    />
  );
}
