"use client";

import { useEffect, useRef, useState } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import useMediaQuery from "@/hooks/ui/useMediaQuery";
import { useGitHubStars } from "@/hooks/useGitHubStars";
import { usePathname } from "@/i18n/navigation";

// Function to control backdrop blur
function toggleBackdrop(show: boolean) {
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
}

export function useNavbar() {
  const pathname = usePathname();
  const isMobileScreen = useMediaQuery("(max-width: 990px)");
  const [activeDropdown, setActiveDropdown] = useState<string | null>(null);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const [isScrolled, setIsScrolled] = useState(false);
  const [menuAnchorX, setMenuAnchorX] = useState(0);
  const [wrapperWidth, setWrapperWidth] = useState(0);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { data: repoData } = useGitHubStars("theexperiencecompany/gaia");

  // GitHub stars: while loading, rapidly cycle random three-digit values so
  // the digits flicker like a slot-machine readout. Initial 100 is stable
  // across SSR/CSR; randomization only runs client-side in the effect.
  const [stars, setStars] = useState(100);
  const isStarsLoading = !repoData?.stargazers_count;
  useEffect(() => {
    if (repoData?.stargazers_count) {
      setStars(Math.round(repoData.stargazers_count));
      return;
    }
    // Slot-machine flicker while the GitHub count loads — but BOUNDED. If the
    // external GitHub API is slow or rate-limited, an unbounded 80ms interval
    // spins the main thread forever: the page never goes idle, which both
    // wastes battery and prevents Lighthouse from ever settling (massively
    // inflating LCP/TBT/TTI). Cap the flicker; NumberFlow animates to the real
    // value once it arrives.
    // A fixed stride through 100..999 reads as a shuffle at 80ms; nothing
    // here needs randomness, so no PRNG is involved.
    const id = setInterval(() => {
      setStars((current) => 100 + ((current * 7 + 173) % 900));
    }, 80);
    const stop = setTimeout(() => clearInterval(id), 1600);
    return () => {
      clearInterval(id);
      clearTimeout(stop);
    };
  }, [repoData?.stargazers_count]);

  const user = useCurrentUser();
  const isAuthenticated = !!user.email;

  // Handle scroll to change navbar appearance
  useEffect(() => {
    const handleScroll = () => {
      const scrollThreshold = 50; // Adjust this value to change when the navbar changes
      setIsScrolled(window.scrollY > scrollThreshold);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Handle mouse leave for navbar container
  const handleNavbarMouseLeave = () => {
    if (isMobileScreen) return;

    setActiveDropdown(null);
    setHoveredItem(null);
    toggleBackdrop(false);
  };

  const handleMouseEnter = (
    menu: string,
    event: React.MouseEvent<HTMLButtonElement>,
  ) => {
    if (isMobileScreen) return;

    const wrapper = wrapperRef.current;
    if (wrapper) {
      const wrapperRect = wrapper.getBoundingClientRect();
      const triggerRect = event.currentTarget.getBoundingClientRect();
      setMenuAnchorX(
        triggerRect.left - wrapperRect.left + triggerRect.width / 2,
      );
      setWrapperWidth(wrapperRect.width);
    }

    setActiveDropdown(menu);
    setHoveredItem(menu);
    toggleBackdrop(true);
  };

  const handleLinkMouseEnter = (label: string) => {
    setHoveredItem(label.toLowerCase());
    setActiveDropdown(null);
    toggleBackdrop(false);
  };

  useEffect(() => {
    setActiveDropdown(null);
    setHoveredItem(null);
    toggleBackdrop(false);

    return () => toggleBackdrop(false);
  }, [pathname]);

  return {
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
  };
}
