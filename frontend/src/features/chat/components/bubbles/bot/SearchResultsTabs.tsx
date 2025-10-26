import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Skeleton } from "@heroui/skeleton";
import { motion } from "framer-motion";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";

import { NewsIcon } from "@/components/shared/icons";
import { useImageDialog } from "@/stores/uiStore";
import {
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
          <ImageResults images={search_results.images} />
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

  useEffect(() => {
    const validateImages = async () => {
      // Filter out obviously invalid images first
      const potentiallyValidImages = images.filter(
        (imageUrl) => imageUrl && typeof imageUrl === "string",
      );

      // Test each image by trying to load it
      const validationPromises = potentiallyValidImages.map(
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
      );

      try {
        const results = await Promise.all(validationPromises);
        const validImageUrls = results.filter(
          (url): url is string => url !== null,
        );
        setValidImages(validImageUrls);
      } catch (error) {
        console.error("Error validating images:", error);
        setValidImages([]);
      }
    };

    if (images && images.length > 0) {
      validateImages();
    } else {
      setValidImages([]);
    }
  }, [images]);

  if (validImages.length === 0) {
    return null;
  }

  return (
    <div className="my-4 flex w-screen max-w-2xl -space-x-15 pr-2">
      {validImages.map((imageUrl, index) => (
        <ImageItem
          key={imageUrl}
          imageUrl={imageUrl}
          index={index}
          onImageClick={() => openDialog(imageUrl)}
          totalImages={validImages.length}
        />
      ))}
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

  return (
    <motion.div
      onClick={onImageClick}
      className={`group cursor-pointer overflow-hidden rounded-2xl shadow-zinc-950 transition-all duration-200 ${
        (index + 1) % 2 == 0
          ? "-rotate-7 hover:-rotate-0"
          : "rotate-7 hover:rotate-0"
      }`}
      style={{
        zIndex: index,
      }}
      initial={{ scale: 0.6, filter: "blur(10px)" }}
      animate={{ scale: 1, filter: "blur(0px)" }}
      transition={{
        delay: index * 0.1,
        duration: 0.1,
        ease: [0.19, 1, 0.22, 1],
        scale: {
          duration: 0.2,
        },
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.zIndex = (totalImages + 10).toString();
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.zIndex = index.toString();
      }}
    >
      {isLoading && (
        <div className="absolute inset-0 z-10">
          <Skeleton className="aspect-square h-full w-full rounded-2xl" />
        </div>
      )}
      <Image
        src={imageUrl}
        alt={`Search result image ${index + 1}`}
        width={700}
        height={700}
        className={`aspect-square h-full bg-zinc-800 object-cover transition ${
          isLoading ? "opacity-0" : "opacity-100"
        }`}
        onLoad={handleLoad}
        priority={index < 3} // Prioritize first 3 images
      />
    </motion.div>
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
              {web.slice(0, 4).map((result, index) => (
                <div
                  key={index}
                  className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-zinc-900 bg-zinc-700"
                >
                  <Image
                    src={`https://www.google.com/s2/favicons?domain=${new URL(result.url).hostname}&sz=64`}
                    alt={`${new URL(result.url).hostname} favicon`}
                    width={16}
                    height={16}
                    className="h-full w-full rounded-full"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      target.style.display = "none";
                    }}
                  />
                </div>
              ))}
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
      {news.map((article, index) => (
        <div
          key={index}
          className="max-w-(--breakpoint-sm) overflow-hidden rounded-lg bg-zinc-800 p-4 shadow-md transition-all hover:shadow-lg"
        >
          <div className="flex flex-row items-center gap-2 text-primary transition-all hover:text-white">
            <NewsIcon
              color={undefined}
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
      {web.map((result, index) => (
        <div
          className="w-full border-b-1 border-b-zinc-700 p-4 pb-3 transition-all hover:bg-white/5"
          key={index}
        >
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
                  src={`https://www.google.com/s2/favicons?domain=${new URL(result.url).hostname}&sz=64`}
                  alt={`${new URL(result.url).hostname} favicon`}
                  width={16}
                  height={16}
                  className="rounded-full"
                  onError={(e) => {
                    const target = e.target as HTMLImageElement;
                    target.style.display = "none";
                  }}
                />
                <a
                  href={result.url}
                  className="max-w-xs truncate text-xs text-primary hover:underline"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {new URL(result.url).hostname}
                </a>
              </span>
              {/* <span className="flex items-center">{timeAgo(result.date)}</span> */}
            </div>
          </a>
        </div>
      ))}
    </div>
  );
}
