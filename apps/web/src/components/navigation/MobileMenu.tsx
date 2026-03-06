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
  auth,
  company,
  connect,
  main,
  product,
  resources,
} from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";

export default function MobileMenu() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const user = useUser();
  const isAuthenticated = user?.email;
  const router = useRouter();

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
          <SheetDescription className="flex flex-col gap-1 pb-20! pt-3 px-6">
            {/* Main navigation links */}
            {main.map((link) =>
              link.external ? (
                <a
                  key={link.href}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                  onClick={() => setSheetOpen(false)}
                >
                  {link.label}
                </a>
              ) : (
                <Link
                  key={link.href}
                  href={link.href}
                  className="py-1.5 text-zinc-200 transition-colors hover:text-white"
                  onClick={() => setSheetOpen(false)}
                >
                  {link.label}
                </Link>
              ),
            )}

            {/* Product Section */}
            <div className="mt-6 flex flex-col gap-0.5">
              <p className="mb-2 text-xs tracking-wide text-zinc-500 uppercase">
                Product
              </p>
              {product.map((link) => {
                const isComingSoon = link.commented;
                if (isComingSoon) {
                  return (
                    <span
                      key={link.href}
                      className="cursor-not-allowed py-1.5 text-sm text-zinc-600 opacity-50 select-none"
                    >
                      {link.label}
                    </span>
                  );
                }
                return link.external ? (
                  <a
                    key={link.href}
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>

            {/* Resources Section */}
            <div className="mt-6 flex flex-col gap-0.5">
              <p className="mb-2 text-xs tracking-wide text-zinc-500 uppercase">
                Resources
              </p>
              {resources.map((link) => {
                const isComingSoon = link.commented;
                if (isComingSoon) {
                  return (
                    <span
                      key={link.href}
                      className="cursor-not-allowed py-1.5 text-sm text-zinc-600 opacity-50 select-none"
                    >
                      {link.label}
                    </span>
                  );
                }
                return link.external ? (
                  <a
                    key={link.href}
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </div>

            {/* Company Section */}
            <div className="mt-6 flex flex-col gap-0.5">
              <p className="mb-2 text-xs tracking-wide text-zinc-500 uppercase">
                Company
              </p>
              {company.map((link) =>
                link.external ? (
                  <a
                    key={link.href}
                    href={link.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                    onClick={() => setSheetOpen(false)}
                  >
                    {link.label}
                  </Link>
                ),
              )}
            </div>

            {/* Connect Section */}
            <div className="mt-6 flex flex-col gap-0.5">
              <p className="mb-2 text-xs tracking-wide text-zinc-500 uppercase">
                Connect
              </p>
              {connect.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  target={link.external ? "_blank" : undefined}
                  rel={link.external ? "noopener noreferrer" : undefined}
                  className="py-1.5 text-sm text-zinc-200 transition-colors hover:text-white"
                  onClick={() => setSheetOpen(false)}
                >
                  {link.label}
                </a>
              ))}
            </div>

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
                          router.push(link.href);
                          setSheetOpen(false);
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
                        onClick={() => setSheetOpen(false)}
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
