"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronDown } from "@/components/shared/icons";
import { LinkButton } from "@/components/shared/LinkButton";
import { appConfig } from "@/config/appConfig";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

const NAVBAR_ITEMS = [
  { type: "dropdown", label: "Product", menu: "product" },
  { type: "link", label: "Pricing", href: "/pricing" },
  { type: "link", label: "Docs", href: "https://docs.heygaia.io" },
  { type: "dropdown", label: "Resources", menu: "resources" },
] as const;

// Desktop nav links — one pass over the config, skipping the Home link.
export function NavbarNavLinks({ pathname }: { pathname: string }) {
  const navLinks: ReactNode[] = [];
  for (const link of appConfig.links.main) {
    if (link.href === "/") continue;
    navLinks.push(
      <LinkButton
        key={link.href}
        size="sm"
        className={`text-sm font-medium ${pathname === link.href ? "text-primary" : "text-zinc-300 hover:text-zinc-100"}`}
        href={link.href}
        startContent={link.icon}
        external={link.external}
      >
        {link.label}
      </LinkButton>,
    );
  }

  return <div className="hidden items-center gap-1 sm:flex">{navLinks}</div>;
}

interface NavbarItemsProps {
  pathname: string;
  hoveredItem: string | null;
  onDropdownMouseEnter: (
    menu: string,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => void;
  onLinkMouseEnter: (label: string) => void;
}

export function NavbarItems({
  pathname,
  hoveredItem,
  onDropdownMouseEnter,
  onLinkMouseEnter,
}: NavbarItemsProps) {
  return (
    <div className="flex items-center gap-1 rounded-lg px-1 py-1">
      {NAVBAR_ITEMS.map((item) =>
        item.type === "link" ? (
          <Link
            key={item.href}
            href={item.href}
            className={`relative flex h-9 cursor-pointer items-center rounded-xl px-4 py-2 text-sm transition-colors hover:bg-zinc-800/40 ${pathname === item.href ? "text-primary" : "text-zinc-300 hover:text-zinc-100"}`}
            onMouseEnter={() => {
              onLinkMouseEnter(item.label);
            }}
            onClick={() => {
              trackEvent(ANALYTICS_EVENTS.NAVIGATION_NAVBAR_LINK_CLICKED, {
                label: item.label,
                href: item.href,
              });
            }}
          >
            <span className="relative z-10">{item.label}</span>
          </Link>
        ) : (
          <button
            type="button"
            key={item.menu}
            className="relative flex h-9 cursor-pointer items-center rounded-xl px-4 py-2 text-sm text-zinc-200 capitalize transition-colors hover:text-zinc-100"
            onMouseEnter={(event) => {
              onDropdownMouseEnter(item.menu, event);
              trackEvent(ANALYTICS_EVENTS.NAVIGATION_NAVBAR_DROPDOWN_OPENED, {
                menu: item.menu,
              });
            }}
          >
            {hoveredItem === item.menu && (
              <div className="absolute inset-0 h-full w-full rounded-xl bg-zinc-800 font-medium!" />
            )}
            <div className="relative z-10 flex items-center gap-2">
              <span>
                {item.label.charAt(0).toUpperCase() + item.label.slice(1)}
              </span>
              <ChevronDown
                height={17}
                width={17}
                className={
                  (hoveredItem === item.menu ? "rotate-180" : "") +
                  " transition duration-200"
                }
              />
            </div>
          </button>
        ),
      )}
    </div>
  );
}
