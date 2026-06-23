import { Skeleton } from "@heroui/skeleton";
import { Tooltip } from "@heroui/tooltip";
import { GlobalIcon } from "@icons";
import Image from "next/image";
import { memo, type ReactNode, useEffect, useRef, useState } from "react";
import {
  usePrefetchUrlMetadata,
  useUrlMetadata,
} from "@/features/chat/hooks/useUrlMetadata";
import { cn } from "@/lib/utils";

// Link chip styling. The bot bubble is dark (bg-zinc-800), so the brand-blue
// `text-primary` link reads fine there. The user bubble is `#00bbff` (the same
// value as `--color-primary`), so blue-on-blue is invisible — there we switch
// to the bubble's black-text treatment with a translucent-black chip.
const DARK_BUBBLE_LINK =
  "bg-primary/20 text-primary hover:text-white hover:underline";
const LIGHT_BUBBLE_LINK = "bg-black/10 text-black underline hover:bg-black/20";

// Global set to track failed image URLs across all instances
const globalFailedUrls = new Set<string>();

const isEmailHref = (href: string) => {
  if (href.startsWith("mailto:")) return true;
  // Linear, non-backtracking email shape check: a single "@" with a "." after
  // it and no whitespace. Avoids the super-linear regex Sonar flags as ReDoS.
  if (/\s/.test(href)) return false;
  const at = href.indexOf("@");
  if (at <= 0 || href.indexOf("@", at + 1) !== -1) return false;
  const dot = href.indexOf(".", at + 1);
  return dot > at + 1 && dot < href.length - 1;
};

const displayHref = (href: string) =>
  href.replace(/^(https?:\/\/|mailto:)/, "");

interface UrlMetadata {
  title: string | null;
  description: string | null;
  favicon: string | null;
  website_name: string | null;
  website_image: string | null;
  url: string;
}

function EmailPreview({
  email,
  name,
  avatar,
  onAvatarError,
}: {
  email: string;
  name: string | null;
  avatar: string | null;
  onAvatarError: (url: string) => void;
}) {
  return (
    <div className="flex w-full items-center gap-3">
      {avatar ? (
        <Image
          width={44}
          height={44}
          alt={name ?? email}
          className="h-11 w-11 shrink-0 rounded-full object-cover"
          src={avatar}
          onError={() => onAvatarError(avatar)}
        />
      ) : (
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-zinc-700 text-lg font-medium text-zinc-300">
          {email[0]?.toUpperCase()}
        </div>
      )}
      <div className="min-w-0">
        {name && (
          <div className="truncate text-sm font-medium text-white">{name}</div>
        )}
        <a
          className="block truncate text-xs text-zinc-400 hover:underline"
          href={`mailto:${email}`}
        >
          {email}
        </a>
      </div>
    </div>
  );
}

function EmailPreviewSkeleton() {
  return (
    <div className="flex w-full items-center gap-3">
      <Skeleton className="h-11 w-11 shrink-0 rounded-full" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Skeleton className="h-4 w-28 rounded" />
        <Skeleton className="h-3 w-40 rounded" />
      </div>
    </div>
  );
}

function WebsiteLoadingSkeleton() {
  return (
    <div className="flex w-full flex-col gap-2">
      {/* Website Image Skeleton */}
      <Skeleton className="relative aspect-video w-full rounded-lg" />

      {/* Website Name & Favicon Skeleton */}
      <div className="flex items-center gap-2">
        <Skeleton className="h-5 w-5 rounded-full" />
        <Skeleton className="h-4 w-32 rounded" />
      </div>

      {/* Title Skeleton */}
      <Skeleton className="h-4 w-full rounded" />

      {/* Description Skeleton (3 lines) */}
      <div className="flex flex-col gap-1">
        <Skeleton className="h-3 w-full rounded" />
        <Skeleton className="h-3 w-full rounded" />
        <Skeleton className="h-3 w-3/4 rounded" />
      </div>

      {/* URL Link Skeleton */}
      <Skeleton className="h-3 w-48 rounded" />
    </div>
  );
}

function WebsiteErrorState() {
  return (
    <div className="flex items-center gap-2 p-3 text-red-400">
      <GlobalIcon className="h-4 w-4" />
      <span className="text-sm">Failed to load preview</span>
    </div>
  );
}

function WebsiteNoPreview() {
  return (
    <div className="flex items-center gap-2 p-3">
      <GlobalIcon className="h-4 w-4 text-gray-400" />
      <span className="text-sm text-gray-400">No preview available</span>
    </div>
  );
}

interface WebsitePreviewProps {
  href: string;
  metadata: UrlMetadata;
  isStreaming: boolean | undefined;
  failedUrls: Set<string>;
  imageLoading: boolean;
  onImageLoad: () => void;
  onImageError: (url: string) => void;
}

function WebsitePreview({
  href,
  metadata,
  isStreaming,
  failedUrls,
  imageLoading,
  onImageLoad,
  onImageError,
}: WebsitePreviewProps) {
  return (
    <div className="flex w-full flex-col gap-2">
      {/* Website Image */}
      {!isStreaming &&
        metadata.website_image &&
        !failedUrls.has(metadata.website_image) && (
          <div className="relative aspect-video w-full overflow-hidden rounded-lg">
            {imageLoading && (
              <Skeleton className="absolute inset-0 z-10 h-full w-full rounded-lg" />
            )}
            <Image
              src={metadata.website_image}
              alt="Website Image"
              layout="responsive"
              width={280}
              height={157}
              objectFit="cover"
              className="rounded-lg"
              onLoadingComplete={onImageLoad}
              onError={() => onImageError(metadata.website_image!)}
            />
          </div>
        )}

      {/* Website Name & Favicon */}
      {(metadata.website_name ||
        (!isStreaming &&
          metadata.favicon &&
          !failedUrls.has(metadata.favicon))) && (
        <div className="flex items-center gap-2">
          {!isStreaming &&
          metadata.favicon &&
          !failedUrls.has(metadata.favicon) ? (
            <Image
              width={20}
              height={20}
              alt="Fav Icon"
              className="h-5 w-5 rounded-full"
              src={metadata.favicon}
              onError={() => onImageError(metadata.favicon!)}
            />
          ) : (
            <GlobalIcon className="h-5 w-5 text-gray-400" />
          )}
          {metadata.website_name && (
            <div className="truncate text-sm font-semibold">
              {metadata.website_name}
            </div>
          )}
        </div>
      )}

      {/* Title */}
      {metadata.title && (
        <div className="truncate text-sm font-medium text-white">
          {metadata.title}
        </div>
      )}

      {/* Description */}
      {metadata.description && (
        <div className="line-clamp-3 text-xs text-gray-400">
          {metadata.description}
        </div>
      )}

      {/* URL Link */}
      <a
        className="truncate text-xs text-primary hover:underline"
        href={href}
        rel="noopener noreferrer"
        target="_blank"
      >
        {displayHref(href)}
      </a>
    </div>
  );
}

function buildTooltipContent(
  href: string,
  isLoading: boolean,
  error: unknown,
  metadata: UrlMetadata | null | undefined,
  isStreaming: boolean | undefined,
  failedUrls: Set<string>,
  imageLoading: boolean,
  onImageLoad: () => void,
  onImageError: (url: string) => void,
): ReactNode {
  if (isEmailHref(href)) {
    if (isLoading) return <EmailPreviewSkeleton />;
    return (
      <EmailPreview
        email={displayHref(href)}
        name={metadata?.title ?? null}
        avatar={
          metadata?.favicon && !failedUrls.has(metadata.favicon)
            ? metadata.favicon
            : null
        }
        onAvatarError={onImageError}
      />
    );
  }
  if (isLoading) return <WebsiteLoadingSkeleton />;
  if (error) return <WebsiteErrorState />;
  if (metadata) {
    return (
      <WebsitePreview
        href={href}
        metadata={metadata}
        isStreaming={isStreaming}
        failedUrls={failedUrls}
        imageLoading={imageLoading}
        onImageLoad={onImageLoad}
        onImageError={onImageError}
      />
    );
  }
  return <WebsiteNoPreview />;
}

const CustomAnchor = memo(
  ({
    href,
    children,
    isStreaming,
    lightBackground,
  }: {
    href: string | undefined;
    children: ReactNode | string | null;
    isStreaming?: boolean;
    lightBackground?: boolean;
  }) => {
    const elementRef = useRef<HTMLAnchorElement>(null);
    const [isInView, setIsInView] = useState(false);
    const [imageLoading, setImageLoading] = useState(true);

    // Only fetch when element is in view
    const {
      data: metadata,
      isLoading,
      error,
    } = useUrlMetadata(isInView ? href : null);
    const prefetchUrlMetadata = usePrefetchUrlMetadata();

    const [failedUrls, setFailedUrls] = useState<Set<string>>(
      () => new Set(globalFailedUrls),
    );

    // Set up intersection observer to detect when element is in view
    useEffect(() => {
      const element = elementRef.current;
      if (!element || !href) return;

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            setIsInView(true);
            // Once we've seen it, we don't need to observe anymore
            observer.unobserve(element);
          }
        },
        {
          rootMargin: "100px", // Start fetching 100px before element comes into view
          threshold: 0.1,
        },
      );

      observer.observe(element);

      return () => {
        observer.unobserve(element);
      };
    }, [href]);

    // Handle prefetching on hover for better UX (only if already in view)
    const handleMouseEnter = () => {
      if (href && isInView && !metadata) {
        prefetchUrlMetadata(href);
      }
    };

    const handleImageError = (url: string) => {
      if (!globalFailedUrls.has(url)) {
        globalFailedUrls.add(url);
        setFailedUrls(new Set(globalFailedUrls));
      }
    };

    if (!href) return null;

    const tooltipContent = buildTooltipContent(
      href,
      isLoading,
      error,
      metadata,
      isStreaming,
      failedUrls,
      imageLoading,
      () => setImageLoading(false),
      handleImageError,
    );

    return (
      <Tooltip
        showArrow
        className="relative max-w-[280px] min-w-[280px] border-2 border-zinc-800 bg-secondary-bg p-3 text-white shadow-lg"
        content={tooltipContent}
      >
        <a
          ref={elementRef}
          href={href}
          className={cn(
            "inline-flex cursor-pointer items-center gap-1 rounded-sm px-1 text-sm font-medium transition-all",
            lightBackground ? LIGHT_BUBBLE_LINK : DARK_BUBBLE_LINK,
          )}
          rel="noopener noreferrer"
          target="_blank"
          onMouseEnter={handleMouseEnter}
        >
          {!isStreaming &&
            metadata?.favicon &&
            !failedUrls.has(metadata.favicon) && (
              <Image
                width={14}
                height={14}
                alt="Favicon"
                className={`h-3.5 w-3.5 shrink-0 ${isEmailHref(href) ? "rounded-full" : "rounded-sm"}`}
                src={metadata.favicon}
                onError={() => handleImageError(metadata.favicon!)}
              />
            )}
          {children}
        </a>
      </Tooltip>
    );
  },
  (prevProps, nextProps) => {
    // Only re-render if href, children, isStreaming, or lightBackground change
    return (
      prevProps.href === nextProps.href &&
      prevProps.children === nextProps.children &&
      prevProps.isStreaming === nextProps.isStreaming &&
      prevProps.lightBackground === nextProps.lightBackground
    );
  },
);

CustomAnchor.displayName = "CustomAnchor";

export default CustomAnchor;
