"use client";

import Image from "next/image";
import React, { useMemo } from "react";

import {
  company,
  connect,
  getLinkDescription,
  product,
  resources,
} from "@/config/appConfig";
import { wallpapers } from "@/config/wallpapers";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

interface NavbarMenuProps {
  activeMenu: string;
}

type InternalHref = React.ComponentProps<typeof Link>["href"];

interface ListItemBaseProps
  extends Omit<React.ComponentPropsWithoutRef<"a">, "href"> {
  title: string;
  children?: React.ReactNode;
  icon?: React.ReactNode;
  /** Render the icon raw, without the default rounded pill background. */
  richIcon?: boolean;
  backgroundImage?: string;
  /** When set with a backgroundImage, anchor the title block to the top instead of the bottom. */
  textPosition?: "top" | "bottom";
  rowSpan?: number;
  colSpan?: number;
}

interface InternalListItemProps extends ListItemBaseProps {
  href: InternalHref;
  external?: false;
}

interface ExternalListItemProps extends ListItemBaseProps {
  href: string;
  external: true;
}

type ListItemProps = InternalListItemProps | ExternalListItemProps;

const menuMap: Record<string, typeof product> = {
  product,
  resources,
  company,
  socials: connect,
};

const gridConfig: Record<string, string> = {
  product: "grid-cols-4",
  resources: "grid-cols-3",
  company: "grid-cols-2 grid-rows-2",
  socials: "grid-cols-3 md:grid-cols-3",
};

const gridStyleConfig: Record<string, React.CSSProperties> = {
  product: { gridTemplateRows: "repeat(4, minmax(0, 1fr))" },
};

interface ProductCellLayout {
  rowSpan?: number;
  colSpan?: number;
  backgroundImage?: string;
  textPosition?: "top" | "bottom";
}

/** Per-link grid placement for the product dropdown.
 *  Grid is 4 cols × 4 rows. Cells flow row-by-row in `product` array order:
 *  Use Cases (col 1, r-span-3), Marketplace (col 2, r-span-3),
 *  Download (col 3, r-span-2), CLI (col 4, r-span-2),
 *  Chat Bots (cols 3-4 row 3, c-span-2),
 *  Row 4: Features | Roadmap | Tailored For Your Role | Compare. */
const PRODUCT_LAYOUT: Record<string, ProductCellLayout> = {
  "/use-cases": {
    rowSpan: 3,
    backgroundImage: wallpapers.useCases.webp,
  },
  "/marketplace": {
    rowSpan: 3,
    backgroundImage: wallpapers.integration.webp,
  },
  "/download": {
    rowSpan: 2,
    backgroundImage: "/images/screenshots/desktop_dock.webp",
    textPosition: "top",
  },
  "/cli": {
    rowSpan: 2,
    backgroundImage: "/images/screenshots/cli.webp",
    textPosition: "top",
  },
  "/bots": {
    colSpan: 2,
  },
};

const ListItem = React.memo(
  React.forwardRef<React.ComponentRef<"a">, ListItemProps>(
    (
      {
        className,
        title,
        children,
        href,
        external,
        icon,
        richIcon,
        backgroundImage,
        textPosition = "bottom",
        rowSpan,
        colSpan,
        ...props
      },
      ref,
    ) => {
      const sharedClassName = cn(
        "group relative flex h-full min-h-18 w-full flex-col overflow-hidden rounded-2xl bg-zinc-800/0 p-3.5 leading-none no-underline transition-all duration-150 select-none hover:bg-zinc-800 hover:text-zinc-100 focus:bg-zinc-800 focus:text-zinc-100",
        textPosition === "top" ? "justify-start" : "justify-center",
        className,
      );
      const content = (
        <>
          {backgroundImage && (
            <>
              <Image
                fill={true}
                src={backgroundImage}
                alt={title}
                sizes="(max-width: 768px) 100vw, (max-width: 1024px) 50vw, 33vw"
                className="absolute inset-0 z-0 object-cover transition-all group-hover:brightness-60"
              />
              <div
                className={cn(
                  "absolute inset-0 z-[1] from-black/90 via-black/50 to-black/20",
                  textPosition === "top"
                    ? "bg-gradient-to-b"
                    : "bg-gradient-to-t",
                )}
              />
            </>
          )}
          <div
            className={cn(
              "flex items-start gap-3",
              backgroundImage && "relative z-[2]",
              backgroundImage && textPosition === "bottom" && "mt-auto",
            )}
          >
            {icon &&
              (richIcon ? (
                <span className="relative flex items-center justify-center text-primary">
                  {icon}
                </span>
              ) : (
                <span
                  className={`relative flex min-h-10 min-w-10 items-center justify-center rounded-xl ${
                    backgroundImage
                      ? "bg-white/5 backdrop-blur group-hover:bg-white/10"
                      : "bg-primary/10 group-hover:bg-primary/15"
                  } p-2 text-primary transition`}
                >
                  {icon}
                </span>
              ))}
            <div className="flex h-full flex-col justify-start gap-1 leading-none font-normal text-zinc-100">
              {title}
              {children && (
                <p
                  className={cn(
                    "line-clamp-2 text-sm leading-tight font-light text-zinc-400",
                    backgroundImage && "relative z-[2]",
                  )}
                >
                  {children}
                </p>
              )}
            </div>
          </div>
        </>
      );

      const liStyle: React.CSSProperties = {};
      if (rowSpan) liStyle.gridRow = `span ${rowSpan} / span ${rowSpan}`;
      if (colSpan) liStyle.gridColumn = `span ${colSpan} / span ${colSpan}`;

      return (
        <li className="list-none" style={liStyle}>
          {external ? (
            <a
              ref={ref}
              className={sharedClassName}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            >
              {content}
            </a>
          ) : (
            <Link
              ref={ref as React.Ref<HTMLAnchorElement>}
              className={sharedClassName}
              href={href}
              // Mega-menu renders 24+ links in the DOM; default prefetch fires
              // an RSC request for each on load, flooding the cold worker and
              // contending with the critical-path download. Prefetch on hover
              // intent instead (Next still prefetches on hover when null).
              prefetch={false}
              {...props}
            >
              {content}
            </Link>
          )}
        </li>
      );
    },
  ),
);

ListItem.displayName = "ListItem";

export function NavbarMenu({ activeMenu }: NavbarMenuProps) {
  const links = useMemo(
    () => (menuMap[activeMenu] ?? []).filter((link) => !link.hideNavbar),
    [activeMenu],
  );

  const gridClass = gridConfig[activeMenu] ?? "grid-cols-3";
  const gridStyle = gridStyleConfig[activeMenu];

  return (
    <div
      className={cn(
        "absolute top-full left-0 z-40 w-full origin-top overflow-hidden rounded-b-2xl border-1 border-y-0 border-white/5 bg-linear-to-b from-zinc-900 to-zinc-900/30 backdrop-blur-xl outline-none",
        "animate-in fade-in zoom-in-95 duration-200",
      )}
    >
      <div className="p-6 pt-2">
        <div className={cn("grid w-full gap-4", gridClass)} style={gridStyle}>
          {links.map((link) => {
            const layout =
              activeMenu === "product" ? PRODUCT_LAYOUT[link.href] : undefined;

            return (
              <ListItem
                key={link.href}
                href={link.href}
                title={link.label}
                external={link.external}
                icon={link.icon}
                richIcon={link.richIcon}
                backgroundImage={layout?.backgroundImage}
                textPosition={layout?.textPosition}
                rowSpan={layout?.rowSpan}
                colSpan={layout?.colSpan}
              >
                {getLinkDescription(link.label)}
              </ListItem>
            );
          })}
        </div>
      </div>
    </div>
  );
}
