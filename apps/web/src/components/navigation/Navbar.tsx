"use client";

import dynamic from "next/dynamic";
import { useNavbar } from "@/hooks/ui/useNavbar";
import { LogoWithContextMenu } from "../shared/LogoWithContextMenu";
import { NavbarActions } from "./NavbarActions";
import { NavbarItems, NavbarNavLinks } from "./NavbarLinks";
import { NavbarMenu } from "./NavbarMenu";

// MobileMenu is lazy-loaded — it is only reachable on small screens.
const MobileMenu = dynamic(() => import("@/components/navigation/MobileMenu"), {
  ssr: false,
});

export default function Navbar() {
  const {
    pathname,
    isMobileScreen,
    activeDropdown,
    hoveredItem,
    isScrolled,
    menuAnchorX,
    wrapperWidth,
    wrapperRef,
    stars,
    isStarsLoading,
    isAuthenticated,
    handleNavbarMouseLeave,
    handleMouseEnter,
    handleLinkMouseEnter,
  } = useNavbar();

  return (
    <div className="fixed top-0 left-0 z-50 w-full px-4 pt-4">
      <div
        ref={wrapperRef}
        className="relative mx-auto w-full max-w-7xl"
        onMouseLeave={handleNavbarMouseLeave}
      >
        <div
          className={`navbar_content flex h-14 w-full items-center justify-between rounded-2xl px-3 transition-all duration-300 ${isScrolled || activeDropdown ? "bg-zinc-900/30 backdrop-blur-md" : "bg-transparent"}`}
        >
          <LogoWithContextMenu className="px-2" />

          <NavbarNavLinks pathname={pathname} />

          {isMobileScreen ? (
            <MobileMenu />
          ) : (
            <NavbarItems
              pathname={pathname}
              hoveredItem={hoveredItem}
              onDropdownMouseEnter={handleMouseEnter}
              onLinkMouseEnter={handleLinkMouseEnter}
            />
          )}

          {isMobileScreen ? (
            <div className="hidden" />
          ) : (
            <NavbarActions
              isAuthenticated={isAuthenticated}
              stars={stars}
              isStarsLoading={isStarsLoading}
            />
          )}
        </div>

        {activeDropdown && (
          <NavbarMenu
            activeMenu={activeDropdown}
            anchorX={menuAnchorX}
            wrapperWidth={wrapperWidth}
          />
        )}
      </div>
    </div>
  );
}
