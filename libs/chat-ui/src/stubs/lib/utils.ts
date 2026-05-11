/**
 * Real utility code copied verbatim from apps/web — pure helpers (cn, debounce, truncateTitle).
 * Not stubbed: chat-ui consumers can rely on these as real impls.
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function truncateTitle(title: string, maxLength = 20): string {
  return title.length > maxLength ? `${title.slice(0, maxLength)}...` : title;
}

export function debounce<F extends (...args: Parameters<F>) => ReturnType<F>>(
  func: F,
  wait: number,
): (...args: Parameters<F>) => void {
  let timeout: ReturnType<typeof setTimeout>;

  return (...args: Parameters<F>) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => func(...args), wait);
  };
}
