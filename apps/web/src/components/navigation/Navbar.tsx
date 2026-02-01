"use client";

import AnimatedNumber from "animated-number-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import MobileMenu from "@/components/navigation/MobileMenu";
import { LinkButton } from "@/components/shared/LinkButton";
import { appConfig } from "@/config/appConfig";
import { useUser } from "@/features/auth/hooks/useUser";
import { useGitHubStars } from "@/hooks";
import useMediaQuery from "@/hooks/ui/useMediaQuery";
import {
  ChevronDown,
  Login02Icon,
  MessageMultiple02Icon,
  StarFilledIcon,
} from "@/icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import { Github } from "../shared";
import { LogoWithContextMenu } from "../shared/LogoWithContextMenu";
import { Button } from "../ui";
import { RaisedButton } from "../ui/raised-button";
import { NavbarMenu } from "./NavbarMenu";

export default function Navbar() {
  const pathname = usePathname();
  const isMobileScreen = useMediaQuery("(max-width: 990px)");
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const [isScrolled, setIsScrolled] = useState(false);
  const { data: repoData } = useGitHubStars("theexperiencecompany/gaia");

  const user = useUser();

  // Handle scroll to change navbar appearance
  useEffect(() => {
    const handleScroll = () => {
      const scrollThreshold = 50; // Adjust this value to change when the navbar changes
      setIsScrolled(window.scrollY > scrollThreshold);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Define navbar items - can be single links or dropdown menus
  const navbarItems = [
    { type: "dropdown", label: "Product", menu: "product" },
    { type: "link", label: "Pricing", href: "/pricing" },
    { type: "link", label: "Manifesto", href: "/manifesto" },
    { type: "dropdown", label: "Resources", menu: "resources" },
    // { type: "link", label: "Download", href: "/download" },
    // { type: "dropdown", label: "Company", menu: "company" },
    // { type: "dropdown", label: "Socials", menu: "socials" },
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
    if (isMobileScreen) return;

    setActiveDropdown(null);
    setHoveredItem(null);
    toggleBackdrop(false);
  };

  const handleMouseEnter = (menu: string) => {
    if (isMobileScreen) return;

    setActiveDropdown(menu);
    setHoveredItem(menu);
    toggleBackdrop(true);
  };

  useEffect(() => {
    setActiveDropdown(null);
    setHoveredItem(null);
    toggleBackdrop(false);

    return () => toggleBackdrop(false);
  }, [pathname]);

  return (
    <div
      className={`fixed top-0 left-0 z-50 w-full px-4 pt-4 transition-all duration-300`}
    >
      <div
        className={`relative mx-auto transition-all duration-300 ${
          isScrolled ? "w-6xl" : "w-full"
        }`}
        onMouseLeave={handleNavbarMouseLeave}
      >
        <div
          className={`navbar_content flex h-14 w-full items-center justify-between px-3 transition-all duration-300 ${
            activeDropdown
              ? "rounded-t-2xl bg-zinc-900"
              : isScrolled
                ? "rounded-2xl bg-zinc-900/30 backdrop-blur-md"
                : "rounded-2xl border-transparent bg-transparent"
          }`}
        >
          <LogoWithContextMenu className="px-2" />

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
                      : "text-zinc-300 hover:text-zinc-100"
                  }`}
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
                        : "text-zinc-300 hover:text-zinc-100"
                    }`}
                    onMouseEnter={() => {
                      setHoveredItem(item.label.toLowerCase());
                      setActiveDropdown(null);
                      toggleBackdrop(false);
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
                    onMouseEnter={() => {
                      handleMouseEnter(item.menu);
                      trackEvent(ANALYTICS_EVENTS.NAVIGATION_NAVBAR_DROPDOWN_OPENED, {
                        menu: item.menu,
                      });
                    }}
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
                href="https://github.com/theexperiencecompany/gaia"
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => {
                  trackEvent(ANALYTICS_EVENTS.NAVIGATION_GITHUB_CLICKED, {
                    source: "navbar",
                  });
                }}
              >
                <Button className="group rounded-xl border-0! bg-black/60 hover:bg-black/40 text-white">
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
                </Button>
              </a>
              <Link href={user.email ? "/c" : "/signup"}>
                <RaisedButton
                  size={"sm"}
                  className="rounded-xl text-black!"
                  color="#00bbff"
                  onClick={() => {
                    trackEvent(ANALYTICS_EVENTS.NAVIGATION_CTA_CLICKED, {
                      is_logged_in: !!user.email,
                      destination: user.email ? "/c" : "/signup",
                    });
                  }}
                >
                  {user.email ? "Chat" : "Get Started"}
                  {user.email ? (
                    <MessageMultiple02Icon width={17} height={17} />
                  ) : (
                    <Login02Icon width={19} height={19} />
                  )}
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
