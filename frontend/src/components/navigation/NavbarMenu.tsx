"use client";

import { motion } from "framer-motion";
import Image from "next/image";
import Link from "next/link";
import React from "react";

import {
  company,
  connect,
  getLinkDescription,
  product,
  resources,
} from "@/config/appConfig";
import { cn } from "@/lib/utils";

interface NavbarMenuProps {
  activeMenu: string;
  onClose: () => void;
}

const ListItem = React.forwardRef<
  React.ComponentRef<"a">,
  React.ComponentPropsWithoutRef<"a"> & {
    title: string;
    children?: React.ReactNode;
    href: string;
    external?: boolean;
    icon?: React.ReactNode;
    backgroundImage?: string;
    rowSpan?: number;
  }
>(
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
    const Component = external ? "a" : Link;
    const linkProps = external
      ? { href, target: "_blank", rel: "noopener noreferrer" }
      : { href };

    return (
      <li className={cn("list-none", rowSpan === 2 && "row-span-2")}>
        <Component
          ref={ref}
          className={cn(
            "group relative flex h-full min-h-18 w-full flex-col justify-center overflow-hidden rounded-2xl bg-zinc-800/0 p-3.5 leading-none no-underline transition-all duration-150 select-none hover:bg-zinc-800 hover:text-zinc-100 focus:bg-zinc-800 focus:text-zinc-100",
            className,
          )}
          {...linkProps}
          {...props}
        >
          {backgroundImage && (
            <>
              <Image
                fill={true}
                src={backgroundImage}
                alt={title}
                className="absolute inset-0 z-0 object-cover transition-all group-hover:brightness-60"
              />
              <div className="absolute inset-0 z-[1] bg-gradient-to-t from-black/90 via-black/50 to-black/20" />
            </>
          )}
          <div
            className={cn(
              "flex items-center gap-2",
              backgroundImage && "relative z-[2] mt-auto",
            )}
          >
            {icon && (
              <span className="relative top-[-1px] flex-shrink-0 rounded-xl bg-zinc-800/80 p-1.5 text-primary transition group-hover:bg-zinc-700/80 group-hover:text-zinc-300">
                {icon}
              </span>
            )}
            <div className="text-base leading-none font-normal text-zinc-100">
              {title}
            </div>
          </div>
          {children && (
            <p
              className={cn(
                "mt-1 line-clamp-2 text-sm leading-tight font-light text-zinc-400",
                backgroundImage && "relative z-[2]",
              )}
            >
              {children}
            </p>
          )}
        </Component>
      </li>
    );
  },
);
ListItem.displayName = "ListItem";

export function NavbarMenu({ activeMenu, onClose }: NavbarMenuProps) {
  const getDescription = (label: string): string => {
    return getLinkDescription(label);
  };

  const getMenuLinks = () => {
    switch (activeMenu) {
      case "product":
        return product;
      case "resources":
        return resources;
      case "company":
        return company;
      case "socials":
        return connect;
      default:
        return [];
    }
  };

  const links = getMenuLinks();

  return (
    <motion.div
      initial={{ scaleY: 0.95, opacity: 0 }}
      animate={{ scaleY: 1, opacity: 1 }}
      exit={{ scaleY: 0.95, opacity: 0 }}
      transition={{
        ease: [0.19, 1, 0.15, 1.01],
      }}
      className={cn(
        "absolute top-full left-0 z-40 w-full origin-top overflow-hidden rounded-b-2xl border-1 border-y-0 border-white/5 bg-gradient-to-b from-zinc-950 to-zinc-900/30 backdrop-blur-2xl outline-none",
      )}
    >
      <div className="p-6">
        {activeMenu === "product" && (
          <div className="grid w-full grid-cols-3 grid-rows-2 gap-4">
            {links.map((link) => (
              <ListItem
                key={link.href}
                href={link.href}
                title={link.label}
                external={link.external}
                icon={link.icon}
                backgroundImage={
                  link.label === "Get Started"
                    ? "/images/wallpapers/surreal.webp"
                    : link.label === "Use Cases"
                      ? "/images/wallpapers/meadow.webp"
                      : undefined
                }
                rowSpan={
                  link.label === "Get Started" || link.label === "Use Cases"
                    ? 2
                    : undefined
                }
              >
                {getDescription(link.label)}
              </ListItem>
            ))}
          </div>
        )}

        {activeMenu === "resources" && (
          <div className="grid w-full grid-cols-2 grid-rows-2 gap-4">
            {links.map((link) => (
              <ListItem
                key={link.href}
                href={link.href}
                title={link.label}
                external={link.external}
                icon={link.icon}
              >
                {getDescription(link.label)}
              </ListItem>
            ))}
          </div>
        )}

        {activeMenu === "company" && (
          <div className="grid w-full grid-cols-2 grid-rows-2 gap-4">
            {links.map((link) => (
              <ListItem
                key={link.href}
                href={link.href}
                title={link.label}
                external={link.external}
                icon={link.icon}
              >
                {getDescription(link.label)}
              </ListItem>
            ))}
          </div>
        )}

        {activeMenu === "socials" && (
          <div className="grid w-full grid-cols-3 gap-4 md:grid-cols-3">
            {links.map((link) => (
              <ListItem
                key={link.href}
                href={link.href}
                title={link.label}
                external={link.external}
                icon={link.icon}
              >
                {getDescription(link.label)}
              </ListItem>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
