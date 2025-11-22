import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";
import { memo, ReactNode, useEffect, useRef, useState } from "react";

import Spinner from "@/components/ui/spinner";
import {
  usePrefetchUrlMetadata,
  useUrlMetadata,
} from "@/features/chat/hooks/useUrlMetadata";
import { GlobalIcon } from "@/icons";

// Global set to track failed image URLs across all instances
const globalFailedUrls = new Set<string>();

const CustomAnchor = memo(
  ({
    href,
    children,
    isStreaming,
  }: {
    href: string | undefined;
    children: ReactNode | string | null;
    isStreaming?: boolean;
  }) => {
    const elementRef = useRef<HTMLAnchorElement>(null);
    const [isInView, setIsInView] = useState(false);

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

    return (
      <Tooltip
        showArrow
        className="relative max-w-[280px] border border-zinc-700 bg-zinc-900 p-3 text-white shadow-lg"
        content={
          isLoading ? (
            <div className="flex justify-center p-5">
              <Spinner />
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 p-3 text-red-400">
              <GlobalIcon className="h-4 w-4" />
              <span className="text-sm">Failed to load preview</span>
            </div>
          ) : metadata ? (
            <div className="flex w-full flex-col gap-2">
              {/* Website Image */}
              {!isStreaming &&
                metadata.website_image &&
                !failedUrls.has(metadata.website_image) && (
                  <div className="relative aspect-video w-full overflow-hidden rounded-lg">
                    <Image
                      src={metadata.website_image}
                      alt="Website Image"
                      layout="responsive"
                      width={280}
                      height={157}
                      objectFit="cover"
                      className="rounded-lg"
                      onError={() => handleImageError(metadata.website_image!)}
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
                      onError={() => handleImageError(metadata.favicon!)}
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
                {href.replace("https://", "").replace("http://", "")}
              </a>
            </div>
          ) : (
            <div className="flex items-center gap-2 p-3">
              <GlobalIcon className="h-4 w-4 text-gray-400" />
              <span className="text-sm text-gray-400">
                No preview available
              </span>
            </div>
          )
        }
      >
        <a
          ref={elementRef}
          href={href}
          className="inline-flex cursor-pointer items-center gap-1 rounded-sm bg-primary/20 px-1 text-sm font-medium text-primary transition-all hover:text-white hover:underline"
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
                className="h-3.5 w-3.5 flex-shrink-0 rounded-sm"
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
    // Only re-render if href, children, or isStreaming actually change
    return (
      prevProps.href === nextProps.href &&
      prevProps.children === nextProps.children &&
      prevProps.isStreaming === nextProps.isStreaming
    );
  },
);

CustomAnchor.displayName = "CustomAnchor";

export default CustomAnchor;
