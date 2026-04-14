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
  backgroundImage?: string;
  rowSpan?: number;
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
  product: "grid-cols-3 grid-rows-3",
  resources: "grid-cols-2 grid-rows-2",
  company: "grid-cols-2 grid-rows-2",
  socials: "grid-cols-3 md:grid-cols-3",
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
        backgroundImage,
        rowSpan,
        ...props
      },
      ref,
    ) => {
      const sharedClassName = cn(
        "group relative flex h-full min-h-18 w-full flex-col justify-center overflow-hidden rounded-2xl bg-zinc-800/0 p-3.5 leading-none no-underline transition-all duration-150 select-none hover:bg-zinc-800 hover:text-zinc-100 focus:bg-zinc-800 focus:text-zinc-100",
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
              <div className="absolute inset-0 z-[1] bg-gradient-to-t from-black/90 via-black/50 to-black/20" />
            </>
          )}
          <div
            className={cn(
              "flex items-start gap-3",
              backgroundImage && "relative z-[2] mt-auto",
            )}
          >
            {icon && (
              <span
                className={`relative flex min-h-10 min-w-10 items-center justify-center rounded-xl ${
                  backgroundImage
                    ? "bg-white/5 backdrop-blur group-hover:bg-white/10"
                    : "bg-zinc-800/80 group-hover:bg-zinc-700/80"
                } p-2 text-primary transition group-hover:text-zinc-300`}
              >
                {icon}
              </span>
            )}
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

      return (
        <li className={cn("list-none", rowSpan === 2 && "row-span-2")}>
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

  return (
    <div
      className={cn(
        "absolute top-full left-0 z-40 w-full origin-top overflow-hidden rounded-b-2xl border-1 border-y-0 border-white/5 bg-linear-to-b from-zinc-900 to-zinc-900/30 backdrop-blur-xl outline-none",
        "animate-in fade-in zoom-in-95 duration-200",
      )}
    >
      <div className="p-6 pt-2">
        <div className={cn("grid w-full gap-4", gridClass)}>
          {links.map((link) => (
            <ListItem
              key={link.href}
              href={link.href}
              title={link.label}
              external={link.external}
              icon={link.icon}
              backgroundImage={
                link.href === "/login"
                  ? "/images/wallpapers/swiss.webp"
                  : link.href === "/use-cases"
                    ? wallpapers.useCases.webp
                    : link.href === "/marketplace"
                      ? wallpapers.integration.webp
                      : undefined
              }
              rowSpan={
                link.href === "/login" ||
                link.href === "/use-cases" ||
                link.href === "/marketplace"
                  ? 2
                  : undefined
              }
            >
              {getLinkDescription(link.label)}
            </ListItem>
          ))}
        </div>
      </div>
    </div>
  );
}
