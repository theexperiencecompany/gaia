"use client";

import { Button } from "@heroui/button";
import { StarFilledIcon } from "@radix-ui/react-icons";
import AnimatedNumber from "animated-number-react";
// Removed framer-motion import to reduce bundle size
import { ChevronDown } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import MobileMenu from "@/components/navigation/MobileMenu";
import { LinkButton } from "@/components/shared/LinkButton";
import { appConfig } from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";
import { useGitHubStars } from "@/hooks";
import useMediaQuery from "@/hooks/ui/useMediaQuery";

import { Github } from "../shared";
import { RaisedButton } from "../ui/shadcn/raised-button";
import { NavbarMenu } from "./NavbarMenu";

export default function Navbar() {
  const pathname = usePathname();
  const isMobileScreen = useMediaQuery("(max-width: 990px)");
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const { data: repoData } = useGitHubStars("heygaia/gaia");

  const user = useUser();

  // Define navbar items - can be single links or dropdown menus
  const navbarItems = [
    { type: "dropdown", label: "Product", menu: "product" },
    { type: "dropdown", label: "Resources", menu: "resources" },
    { type: "link", label: "Pricing", href: "/pricing" },
    { type: "dropdown", label: "Company", menu: "company" },
    { type: "dropdown", label: "Socials", menu: "socials" },
  ] as const;

  // Function to control backdrop blur
  const toggleBackdrop = (show: boolean) => {
    const backdrop = document.getElementById("navbar-backdrop");
    if (backdrop) {
      if (show) {
        backdrop.style.opacity = "1";
        backdrop.style.pointerEvents = "none";
      } else {
        backdrop.style.opacity = "0";
        backdrop.style.pointerEvents = "none";
      }
    }
  };

  // Handle mouse leave for navbar container
  const handleNavbarMouseLeave = () => {
    if (!isMobileScreen) {
      setActiveDropdown(null);
      setHoveredItem(null);
      toggleBackdrop(false);
    }
  };

  const handleMouseEnter = (menu: string) => {
    if (!isMobileScreen) {
      setActiveDropdown(menu);
      setHoveredItem(menu);
      toggleBackdrop(true);
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      toggleBackdrop(false);
    };
  }, []);

  return (
    <div className="fixed top-0 left-0 z-50 w-full px-4 pt-4">
      <div
        className="relative mx-auto max-w-6xl"
        onMouseLeave={handleNavbarMouseLeave}
      >
        <div
          className={`navbar_content flex h-14 w-full items-center justify-between border-1 border-white/5 px-3 backdrop-blur-md transition-none ${
            activeDropdown
              ? "rounded-t-2xl border-b-0 bg-zinc-950"
              : "rounded-2xl bg-zinc-900/30"
          }`}
          // style={activeDropdown ? { backgroundColor: "#08090A" } : {}}
        >
          <Button
            as={Link}
            href={"/"}
            variant="light"
            className="h-10 w-10 px-12!"
          >
            <Image
              src="/images/logos/logo.webp"
              alt="GAIA Logo"
              width={25}
              height={25}
              className="min-w-[25px]"
            />
            <span className="tracking-tigher text-xl font-medium">GAIA</span>
          </Button>

          <div className="hidden items-center gap-1 sm:flex">
            {appConfig.links.main
              .filter((link) => link.href !== "/") // Filter out Home link for desktop nav
              .map(({ href, label, icon, external }) => (
                <LinkButton
                  key={href}
                  size="sm"
                  className={`text-sm font-medium ${
                    pathname === href
                      ? "text-primary"
                      : "text-zinc-400 hover:text-zinc-300"
                  }`}
                  as={Link}
                  href={href}
                  startContent={icon}
                  external={external}
                >
                  {label}
                </LinkButton>
              ))}
          </div>

          {isMobileScreen ? (
            <MobileMenu />
          ) : (
            <div className="flex items-center gap-1 rounded-lg px-1 py-1">
              {navbarItems.map((item) =>
                item.type === "link" ? (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`relative flex h-9 cursor-pointer items-center rounded-xl px-4 py-2 text-sm transition-colors hover:bg-zinc-800/40 ${
                      pathname === item.href
                        ? "text-primary"
                        : "text-zinc-400 hover:text-zinc-100"
                    }`}
                    onMouseEnter={() => {
                      setHoveredItem(item.label.toLowerCase());
                      setActiveDropdown(null);
                      toggleBackdrop(false);
                    }}
                  >
                    {/* {hoveredItem === item.label.toLowerCase() && (
                      <div className="absolute inset-0 h-full w-full rounded-lg bg-zinc-800/40 font-medium! transition-all! duration-300 ease-out" />
                    )} */}
                    <span className="relative z-10">{item.label}</span>
                  </Link>
                ) : (
                  <button
                    key={item.menu}
                    className="relative flex h-9 cursor-pointer items-center rounded-xl px-4 py-2 text-sm text-zinc-400 capitalize transition-colors hover:text-zinc-100"
                    onMouseEnter={() => handleMouseEnter(item.menu)}
                  >
                    {hoveredItem === item.menu && (
                      <div className="absolute inset-0 h-full w-full rounded-xl bg-zinc-800 font-medium! transition-all duration-300 ease-out" />
                    )}
                    <div className="relative z-10 flex items-center gap-2">
                      <span>
                        {item.label.charAt(0).toUpperCase() +
                          item.label.slice(1)}
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
          )}

          {isMobileScreen ? (
            <div className="hidden" />
          ) : (
            <div className="group hidden items-center gap-3 sm:flex">
              <a
                href="https://github.com/heygaia/gaia"
                target="_blank"
                rel="noopener noreferrer"
              >
                <RaisedButton
                  size={"sm"}
                  className="group rounded-xl border-0!"
                  color="#1c1c1c"
                >
                  <div className="flex items-center">
                    <Github className="mr-1 size-4 fill-white" />
                    <span className="ml-1 lg:hidden">Star</span>
                    <span className="ml-1 hidden lg:inline">GitHub</span>
                  </div>
                  <div className="flex items-center gap-1 text-sm">
                    <StarFilledIcon className="relative top-px size-4 text-white group-hover:text-yellow-300" />
                    <span className="font-medium text-white">
                      <AnimatedNumber
                        value={repoData?.stargazers_count.toFixed(0)}
                        className="font-medium text-white"
                        duration={1000}
                        formatValue={(n: number) => Math.round(n).toString()}
                      />
                    </span>
                  </div>
                </RaisedButton>
              </a>
              <Link href={user.email ? "/c" : "/signup"}>
                <RaisedButton
                  size={"sm"}
                  className="rounded-xl text-black!"
                  color="#00bbff"
                >
                  {user.email ? "Open Chat" : "Get Started"}
                </RaisedButton>
                {/* #1c1c1c */}
              </Link>
            </div>
          )}
        </div>

        {activeDropdown && (
          <NavbarMenu
            activeMenu={activeDropdown}
            // onClose={() => setActiveDropdown(null)}
          />
        )}
      </div>
    </div>
  );
}
