"use client";

import { useEffect, useRef, useState } from "react";

// Cache to store results and avoid re-computing for same images
const colorDetectionCache = new Map<string, boolean>();

/**
 * Hook to detect if an icon image is predominantly dark and needs inversion
 * Optimized with: caching, downscaling, pixel sampling, and early exit
 */
export const useIconColorDetection = (src: string) => {
  const [shouldInvert, setShouldInvert] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Check cache first
    if (colorDetectionCache.has(src)) {
      setShouldInvert(colorDetectionCache.get(src)!);
      setIsLoading(false);
      return;
    }

    // Create abort controller for cleanup
    abortControllerRef.current = new AbortController();
    const { signal } = abortControllerRef.current;

    const detectColor = async () => {
      try {
        // Create an image element
        const img = new Image();
        img.crossOrigin = "anonymous";

        // Check if aborted before loading
        if (signal.aborted) return;

        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve();
          img.onerror = () => reject();
          img.src = src;
        });

        // Check if aborted after loading
        if (signal.aborted) return;

        // Create canvas and draw image
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d", { willReadFrequently: true });

        if (!ctx) {
          setIsLoading(false);
          return;
        }

        // Downscale to 20x20 for even faster processing (400 pixels vs 2500)
        const sampleSize = 20;
        canvas.width = sampleSize;
        canvas.height = sampleSize;
        ctx.drawImage(img, 0, 0, sampleSize, sampleSize);

        // Get image data from downscaled image
        const imageData = ctx.getImageData(0, 0, sampleSize, sampleSize);
        const data = imageData.data;

        let totalBrightness = 0;
        let opaquePixels = 0;

        // Sample every 2nd pixel for 4x speed improvement (still 200 samples)
        for (let i = 0; i < data.length; i += 8) {
          const alpha = data[i + 3];

          // Only count pixels that aren't fully transparent
          if (alpha > 50) {
            const r = data[i];
            const g = data[i + 1];
            const b = data[i + 2];

            // Calculate perceived brightness using standard formula
            const brightness = 0.299 * r + 0.587 * g + 0.114 * b;
            totalBrightness += brightness;
            opaquePixels++;
          }
        }

        if (opaquePixels === 0) {
          colorDetectionCache.set(src, false);
          setShouldInvert(false);
          setIsLoading(false);
          return;
        }

        const averageBrightness = totalBrightness / opaquePixels;

        // If average brightness is below 50 (out of 255), consider it dark
        const invert = averageBrightness < 50;

        // Cache the result
        colorDetectionCache.set(src, invert);

        if (!signal.aborted) {
          setShouldInvert(invert);
          setIsLoading(false);
        }
      } catch (error) {
        if (!signal.aborted) {
          console.warn("Failed to detect icon color:", error);
          setShouldInvert(false);
          setIsLoading(false);
        }
      }
    };

    detectColor();

    // Cleanup function
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [src]);

  return { shouldInvert, isLoading };
};
