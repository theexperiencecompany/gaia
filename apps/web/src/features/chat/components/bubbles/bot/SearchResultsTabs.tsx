import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Skeleton } from "@heroui/skeleton";
import { CircleArrowRight02Icon, NewsIcon } from "@icons";
import * as m from "motion/react-m";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { safeUrl } from "@/features/chat/utils/safeUrl";
import { useImageDialog } from "@/stores/uiStore";
import type {
  ImageResult,
  NewsResult,
  SearchResults,
  WebResult,
} from "@/types/features/convoTypes";

interface SearchResultsTabsProps {
  search_results: SearchResults;
}

export default function SearchResultsTabs({
  search_results,
}: SearchResultsTabsProps) {
  return (
    <div className="w-full">
      <div className="space-y-6">
        {search_results.web && search_results.web?.length > 0 && (
          <SourcesButton web={search_results.web} />
        )}

        {search_results.images && search_results.images?.length > 0 && (
          <ImageResults
            // Keyed by payload so a new result set remounts the component,
            // resetting validation and paging state without effect-based resets.
            key={search_results.images.join("|")}
            images={search_results.images}
          />
        )}

        {search_results.news && search_results.news?.length > 0 && (
          <NewsResults news={search_results.news} />
        )}
      </div>
    </div>
  );
}

interface ImageResultsProps {
  images: ImageResult[];
}

function ImageResults({ images }: ImageResultsProps) {
  const { openDialog } = useImageDialog();
  const [validImages, setValidImages] = useState<string[]>([]);
  const [startIndex, setStartIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const validateImages = async () => {
      // Test each image by trying to load it
      const results = await Promise.all(
        images.map(
          (imageUrl) =>
            new Promise<string | null>((resolve) => {
              const img = new window.Image();

              const timeoutId = setTimeout(() => {
                resolve(null); // Timeout after 5 seconds
              }, 5000);

              img.onload = () => {
                clearTimeout(timeoutId);
                resolve(imageUrl);
              };

              img.onerror = () => {
                clearTimeout(timeoutId);
                resolve(null);
              };

              img.src = imageUrl;
            }),
        ),
      );
      if (cancelled) return;
      setValidImages(results.filter((url): url is string => url !== null));
    };

    validateImages().catch((error: unknown) => {
      console.error("Error validating images:", error);
      if (!cancelled) setValidImages([]);
    });

    return () => {
      cancelled = true;
    };
  }, [images]);

  if (validImages.length === 0) {
    return null;
  }

  const MAX_VISIBLE = 5;
  const displayImages = validImages.slice(startIndex, startIndex + MAX_VISIBLE);
  const remaining = validImages.length - (startIndex + MAX_VISIBLE);
  // Always show a count — on the last page wrap around to show first batch size
  const nextBatchCount =
    remaining > 0
      ? remaining
      : Math.min(MAX_VISIBLE, validImages.length - MAX_VISIBLE);

  const cycleNext = () => {
    const nextStart = startIndex + MAX_VISIBLE;
    setStartIndex(nextStart >= validImages.length ? 0 : nextStart);
  };

  return (
    <div className="my-4 flex items-center -space-x-14">
      {displayImages.map((imageUrl, index) => (
        <ImageItem
          key={imageUrl}
          imageUrl={imageUrl}
          index={index}
          totalImages={displayImages.length}
          onImageClick={() => openDialog(imageUrl)}
        />
      ))}
      {validImages.length > MAX_VISIBLE && (
        <Button
          onPress={cycleNext}
          className="relative z-10 flex h-32 w-32 shrink-0 flex-col items-center justify-center gap-1.5 rounded-2xl bg-zinc-800/80 text-zinc-300 shadow-sm backdrop-blur-sm transition-colors hover:bg-zinc-700/80 hover:text-white"
          variant="flat"
          style={{
            rotate: displayImages.length % 2 === 0 ? "8deg" : "-8deg",
          }}
        >
          <span className="text-base font-semibold">+{nextBatchCount}</span>
          <CircleArrowRight02Icon
            width={16}
            height={16}
            className="opacity-70"
          />
        </Button>
      )}
    </div>
  );
}

interface ImageItemProps {
  imageUrl: string;
  index: number;
  onImageClick: () => void;
  totalImages: number;
}

function ImageItem({
  imageUrl,
  index,
  onImageClick,
  totalImages,
}: ImageItemProps) {
  const [isLoading, setIsLoading] = useState(true);

  const handleLoad = useCallback(() => {
    setIsLoading(false);
  }, []);

  const rotation =
    totalImages > 1 ? (index % 2 === 0 ? "8deg" : "-8deg") : "0deg";

  return (
    <m.div
      onClick={onImageClick}
      className="relative h-32 w-32 shrink-0 cursor-pointer overflow-hidden rounded-2xl shadow-zinc-950 transition-transform duration-200 hover:scale-105 hover:z-10"
      style={{ rotate: rotation, zIndex: index }}
      initial={{ scale: 0.6, filter: "blur(10px)" }}
      animate={{ scale: 1, filter: "blur(0px)" }}
      transition={{
        delay: index * 0.07,
        duration: 0.15,
        ease: [0.19, 1, 0.22, 1],
      }}
    >
      {isLoading && (
        <div className="absolute inset-0 z-10">
          <Skeleton className="h-full w-full rounded-2xl" />
        </div>
      )}
      <Image
        src={imageUrl}
        alt={`Search result image ${index + 1}`}
        width={112}
        height={112}
        className={`h-full w-full bg-zinc-800 object-cover transition ${isLoading ? "opacity-0" : "opacity-100"}`}
        onLoad={handleLoad}
        priority={index < 3}
      />
    </m.div>
  );
}

interface SourcesButtonProps {
  web: WebResult[];
}

function SourcesButton({ web }: SourcesButtonProps) {
  return (
    <div className="flex justify-start">
      <Popover placement="top" showArrow disableAnimation backdrop="opaque">
        <PopoverTrigger>
          <Button variant="flat" radius="full" size="sm">
            <div className="flex -space-x-3">
              {web.slice(0, 4).map((result) => {
                const host = safeUrl(result.url)?.hostname;
                return (
                  <div
                    key={result.url + result.title}
                    className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-zinc-900 bg-zinc-700"
                  >
                    {host && (
                      <Image
                        src={`https://www.google.com/s2/favicons?domain=${host}&sz=64`}
                        alt={`${host} favicon`}
                        width={16}
                        height={16}
                        className="h-full w-full rounded-full"
                        onError={(e) => {
                          const target = e.target as HTMLImageElement;
                          target.style.display = "none";
                        }}
                      />
                    )}
                  </div>
                );
              })}
            </div>
            <span className="font-medium text-zinc-300">Search Results</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent className="bg-transparent p-0! shadow-none">
          <WebResults web={web} />
        </PopoverContent>
      </Popover>
    </div>
  );
}

interface NewsResultsProps {
  news: NewsResult[];
}

function NewsResults({ news }: NewsResultsProps) {
  return (
    <div className="space-y-2">
      {news.map((article) => (
        <div
          key={article.url + article.title}
          className="max-w-(--breakpoint-sm) overflow-hidden rounded-lg bg-zinc-800 p-4 shadow-md transition-shadow hover:shadow-lg"
        >
          <div className="flex flex-row items-center gap-2 text-primary transition-colors hover:text-white">
            <NewsIcon
              height={20}
              width={20}
              className="size-[20px] min-w-[20px]"
            />
            <h2 className="truncate text-lg font-medium">
              <a href={article.url} target="_blank" rel="noopener noreferrer">
                {article.title}
              </a>
            </h2>
          </div>
          <p className="mb-1 line-clamp-2 text-sm text-foreground-700">
            {article.content}
          </p>
          <div className="flex flex-wrap items-center gap-x-4 text-sm text-foreground-500">
            <span className="text-xs">Score: {article.score?.toFixed(2)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

interface WebResultsProps {
  web: WebResult[];
}

function WebResults({ web }: WebResultsProps) {
  return (
    <div className="max-h-80 w-full max-w-lg overflow-y-auto rounded-2xl bg-zinc-800/70 backdrop-blur-2xl">
      {web.map((result) => {
        const url = safeUrl(result.url);
        const host = url?.hostname;
        return (
          <div
            className="w-full border-b-1 border-b-zinc-700 p-4 pb-3 transition-colors hover:bg-white/5"
            key={result.url + result.title}
          >
            {url ? (
              <a
                href={result.url}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full space-y-1"
              >
                <h2 className="truncate text-sm font-medium">{result.title}</h2>
                <p className="line-clamp-2 text-xs text-foreground-500">
                  {result.content}
                </p>
                <div className="flex flex-wrap items-center gap-x-4 text-sm">
                  <span className="flex items-center gap-2">
                    <Image
                      src={`https://www.google.com/s2/favicons?domain=${host}&sz=64`}
                      alt={`${host} favicon`}
                      width={16}
                      height={16}
                      className="rounded-full"
                      onError={(e) => {
                        const target = e.target as HTMLImageElement;
                        target.style.display = "none";
                      }}
                    />
                    <span className="max-w-xs truncate text-xs text-primary hover:underline">
                      {host}
                    </span>
                  </span>
                  {/* <span className="flex items-center">{timeAgo(result.date)}</span> */}
                </div>
              </a>
            ) : (
              <div className="w-full space-y-1">
                <h2 className="truncate text-sm font-medium text-foreground-500">
                  {result.title}
                </h2>
                <p className="line-clamp-2 text-xs text-foreground-500">
                  {result.content}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
