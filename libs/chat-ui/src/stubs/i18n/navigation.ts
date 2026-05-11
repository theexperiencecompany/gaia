/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 *
 * Real impl uses next-intl's createNavigation. This stub provides a minimal
 * shape so consumer hooks can compile without pulling in next/navigation.
 */
import type { ComponentType, ReactNode } from "react";

type LinkProps = {
  href: string;
  locale?: string;
  children?: ReactNode;
} & Record<string, unknown>;

const noopComponent: ComponentType<LinkProps> = (() => null) as ComponentType<
  LinkProps
>;

interface RouterLike {
  push: (href: string, options?: { locale?: string }) => void;
  replace: (href: string, options?: { locale?: string }) => void;
  prefetch: (href: string) => void;
  back: () => void;
  forward: () => void;
  refresh: () => void;
}

const noopRouter: RouterLike = Object.freeze({
  push: () => {},
  replace: () => {},
  prefetch: () => {},
  back: () => {},
  forward: () => {},
  refresh: () => {},
});

export const Link = noopComponent;

export const redirect = (_href: string, _options?: { locale?: string }): void => {};

export const usePathname = (): string => "/";

export const useRouter = (): RouterLike => noopRouter;

export const useParams = <T extends Record<string, string | string[]>>(): T =>
  ({}) as T;
