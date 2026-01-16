"use client";

import { useEffect, useRef, useState } from "react";

import { useTheme } from "@/components/providers/ThemeProvider";

// Cache to store brightness values (not inversion decision) and avoid re-computing for same images
const brightnessCache = new Map<string, number>();

/**
 * Hook to detect if an icon image needs inversion based on theme
 * In dark mode: invert if icon is too dark (brightness < 50)
 * In light mode: invert if icon is too light (brightness > 200)
 * Optimized with: caching, downscaling, pixel sampling, and early exit
 */
export const useIconColorDetection = (src: string) => {
  const [shouldInvert, setShouldInvert] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const abortControllerRef = useRef<AbortController | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    const isDarkMode = resolvedTheme === "dark";

    // Check cache first for brightness
    if (brightnessCache.has(src)) {
      const brightness = brightnessCache.get(src)!;
      // In dark mode, invert dark icons. In light mode, invert light icons.
      const invert = isDarkMode ? brightness < 50 : brightness > 200;
      setShouldInvert(invert);
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
          brightnessCache.set(src, 128); // Default to mid brightness
          setShouldInvert(false);
          setIsLoading(false);
          return;
        }

        const averageBrightness = totalBrightness / opaquePixels;

        // Cache the brightness value (not the inversion decision)
        brightnessCache.set(src, averageBrightness);

        // In dark mode, invert dark icons. In light mode, invert light icons.
        const invert = isDarkMode
          ? averageBrightness < 50
          : averageBrightness > 200;

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
  }, [src, resolvedTheme]);

  return { shouldInvert, isLoading };
};
