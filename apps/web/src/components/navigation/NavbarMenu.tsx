"use client";

import { ArrowUpRight01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useRef } from "react";

import { type AppLink, product, resources } from "@/config/appConfig";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

const MENUS: Record<
  string,
  { links: AppLink[]; width: number; columns: 1 | 2 }
> = {
  product: { links: product, width: 640, columns: 2 },
  resources: { links: resources, width: 360, columns: 1 },
};

const MENU_ORDER = Object.keys(MENUS);
const EDGE_MARGIN = 8;

const swipeVariants = {
  enter: (direction: number) => ({ x: direction * 32, opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (direction: number) => ({ x: direction * -32, opacity: 0 }),
};

interface NavbarMenuProps {
  activeMenu: string;
  /** Horizontal center of the hovered trigger, relative to the navbar wrapper. */
  anchorX: number;
  /** Width of the navbar wrapper, used to keep the panel inside it. */
  wrapperWidth: number;
}

function MenuItem({ link }: { link: AppLink }) {
  const content = (
    <>
      {link.icon &&
        (link.richIcon ? (
          <span className="flex min-h-10 min-w-10 items-center justify-center text-primary">
            {link.icon}
          </span>
        ) : (
          <span className="flex min-h-10 min-w-10 items-center justify-center rounded-xl bg-primary/10 p-2 text-primary transition group-hover:bg-primary/15">
            {link.icon}
          </span>
        ))}
      <span className="flex flex-col gap-0.5">
        <span className="flex items-center gap-1 text-sm text-zinc-100">
          {link.label}
          {link.external && (
            <ArrowUpRight01Icon
              width={13}
              height={13}
              className="text-zinc-500"
            />
          )}
        </span>
        {link.description && (
          <span className="line-clamp-1 text-xs font-light text-zinc-400">
            {link.description}
          </span>
        )}
      </span>
    </>
  );

  const className =
    "group flex w-full items-center gap-3 rounded-xl p-2 pr-3 no-underline transition-colors hover:bg-zinc-800";

  return (
    <li className="list-none">
      {link.external ? (
        <a
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          className={className}
        >
          {content}
        </a>
      ) : (
        // The panel holds many links; prefetch on hover intent only.
        <Link href={link.href} prefetch={false} className={className}>
          {content}
        </Link>
      )}
    </li>
  );
}

export function NavbarMenu({
  activeMenu,
  anchorX,
  wrapperWidth,
}: NavbarMenuProps) {
  const index = MENU_ORDER.indexOf(activeMenu);
  const prevIndexRef = useRef(index);
  const direction = index >= prevIndexRef.current ? 1 : -1;

  useEffect(() => {
    prevIndexRef.current = index;
  }, [index]);

  const menu = MENUS[activeMenu];
  if (!menu) return null;

  const links = menu.links.filter((link) => !link.hideNavbar);
  const left = Math.min(
    Math.max(anchorX - menu.width / 2, EDGE_MARGIN),
    Math.max(wrapperWidth - menu.width - EDGE_MARGIN, EDGE_MARGIN),
  );

  return (
    <div
      className="absolute top-full z-40 pt-2 transition-[left,width] duration-300 ease-out"
      style={{ left, width: menu.width }}
    >
      <div className="overflow-hidden rounded-2xl border border-white/5 bg-zinc-900/60 shadow-2xl backdrop-blur-2xl">
        <AnimatePresence mode="wait" initial={false} custom={direction}>
          <m.div
            key={activeMenu}
            custom={direction}
            variants={swipeVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="p-2"
          >
            <ul
              className={cn(
                "gap-1",
                menu.columns === 2 ? "grid grid-cols-2" : "flex flex-col",
              )}
            >
              {links.map((link) => (
                <MenuItem key={link.href} link={link} />
              ))}
            </ul>
          </m.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
