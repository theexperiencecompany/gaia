"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  COPY_VARIANTS,
  GALLERY_STATES,
  GALLERY_VIEWS,
  type GalleryState,
  LAYOUT_VARIANTS,
} from "./fixtures";

const pick = <T extends string>(
  value: string | null,
  options: readonly T[],
): T => options.find((option) => option === value) ?? options[0];

/** The gallery's selection lives in the URL so every combination has a screenshot-able address. */
export function useGalleryParams() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const selection = {
    view: pick(params.get("view"), GALLERY_VIEWS),
    layout: pick(params.get("layout"), LAYOUT_VARIANTS),
    copy: pick(params.get("copy"), COPY_VARIANTS),
    state: pick<GalleryState>(params.get("state"), GALLERY_STATES),
  };

  const set = (key: keyof typeof selection, value: string) => {
    const next = new URLSearchParams(params.toString());
    next.set(key, value);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  return { ...selection, set };
}
