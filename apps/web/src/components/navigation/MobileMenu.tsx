"use client";

import { Menu01Icon } from "@icons";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  type AppLink,
  auth,
  company,
  connect,
  product,
  resources,
} from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

const LINK_CLASS =
  "py-1.5 text-sm text-zinc-200 transition-colors hover:text-white";

function MobileMenuLink({
  link,
  onNavigate,
}: {
  link: AppLink;
  onNavigate: () => void;
}) {
  if (link.commented) {
    return (
      <span className="cursor-not-allowed py-1.5 text-sm text-zinc-600 opacity-50 select-none">
        {link.label}
      </span>
    );
  }
  if (link.external) {
    return (
      <a
        href={link.href}
        target="_blank"
        rel="noopener noreferrer"
        className={LINK_CLASS}
        onClick={onNavigate}
      >
        {link.label}
      </a>
    );
  }
  return (
    <Link href={link.href} className={LINK_CLASS} onClick={onNavigate}>
      {link.label}
    </Link>
  );
}

const GENERAL_LINKS: AppLink[] = [
  { label: "Pricing", href: "/pricing" },
  { label: "About", href: "/about" },
  { label: "Docs", href: "https://docs.heygaia.io", external: true },
];

export default function MobileMenu() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const user = useUser();
  const isAuthenticated = user?.email;
  const router = useRouter();
  const closeSheet = () => setSheetOpen(false);

  const sections: { title: string; links: AppLink[] }[] = [
    { title: "Product", links: product.filter((link) => !link.hideNavbar) },
    { title: "General", links: GENERAL_LINKS },
    { title: "Resources", links: resources.filter((link) => !link.hideNavbar) },
    { title: "Company", links: company },
    { title: "Connect", links: connect },
  ];

  return (
    <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
      <SheetTrigger aria-label="Menu trigger">
        <div className="rounded-full p-3">
          <Menu01Icon color="foreground" />
        </div>
      </SheetTrigger>
      <SheetContent className="z-100 w-full overflow-y-auto! border-none bg-zinc-950/50 backdrop-blur-2xl text-foreground dark">
        <SheetHeader>
          <SheetTitle>
            <VisuallyHidden.Root>Menu</VisuallyHidden.Root>
          </SheetTitle>
          <SheetDescription className="flex flex-col gap-1 pb-20! pt-8 px-6">
            {sections.map((section) => (
              <div key={section.title} className="mt-6 flex flex-col gap-0.5">
                <p className="mb-2 text-xs tracking-wide text-zinc-500 uppercase">
                  {section.title}
                </p>
                {section.links.map((link) => (
                  <MobileMenuLink
                    key={link.href}
                    link={link}
                    onNavigate={closeSheet}
                  />
                ))}
              </div>
            ))}

            {/* Authentication links */}
            <div className="mt-8 flex flex-col gap-2">
              {isAuthenticated
                ? auth
                    .filter((link) => link.requiresAuth)
                    .map((link) => (
                      <button
                        key={link.href}
                        type="button"
                        className="text-left text-sm font-semibold text-primary transition-colors hover:text-primary"
                        onClick={() => {
                          trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
                            is_logged_in: Boolean(isAuthenticated),
                            destination: link.href,
                          });
                          router.push(link.href);
                          closeSheet();
                        }}
                      >
                        {link.label}
                      </button>
                    ))
                : auth
                    .filter((link) => link.guestOnly)
                    .map((link) => (
                      <Link
                        key={link.href}
                        href={link.href}
                        className="text-sm font-semibold text-primary transition-colors hover:text-primary"
                        onClick={() => {
                          trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
                            is_logged_in: Boolean(isAuthenticated),
                            destination: link.href,
                          });
                          closeSheet();
                        }}
                      >
                        {link.label}
                      </Link>
                    ))}
            </div>
          </SheetDescription>
        </SheetHeader>
      </SheetContent>
    </Sheet>
  );
}
