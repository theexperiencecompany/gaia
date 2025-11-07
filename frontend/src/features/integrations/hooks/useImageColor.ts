import { useEffect, useState } from "react";
import tinycolor from "tinycolor2";

/**
 * Extract the dominant color from an image URL
 */
export const useImageColor = (
  imageUrl: string | null,
  brightness?: number,
  opacity?: number,
) => {
  const [color, setColor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!imageUrl) {
      setIsLoading(false);
      return;
    }

    const extractColor = async () => {
      try {
        // Create a canvas element
        const img = new Image();
        img.crossOrigin = "Anonymous";

        img.onload = () => {
          const canvas = document.createElement("canvas");
          const ctx = canvas.getContext("2d");

          if (!ctx) {
            setIsLoading(false);
            return;
          }

          // Set canvas size to match image
          canvas.width = img.width;
          canvas.height = img.height;

          // Draw image on canvas
          ctx.drawImage(img, 0, 0);

          // Get image data
          const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const data = imageData.data;

          // Count color occurrences (sampling every 10th pixel for performance)
          const colorMap: { [key: string]: number } = {};
          for (let i = 0; i < data.length; i += 40) {
            // RGBA - skip very transparent or very light/dark pixels
            const r = data[i];
            const g = data[i + 1];
            const b = data[i + 2];
            const a = data[i + 3];

            // Skip transparent pixels
            if (a < 50) continue;

            // Skip very light or very dark pixels
            const brightness = (r + g + b) / 3;
            if (brightness > 240 || brightness < 15) continue;

            const rgb = `${r},${g},${b}`;
            colorMap[rgb] = (colorMap[rgb] || 0) + 1;
          }

          // Find most common color
          let maxCount = 0;
          let dominantColor = "147, 51, 234"; // Default purple

          for (const [rgb, count] of Object.entries(colorMap)) {
            if (count > maxCount) {
              maxCount = count;
              dominantColor = rgb;
            }
          }

          // Convert to hex and adjust for better visibility
          const [r, g, b] = dominantColor.split(",").map(Number);
          const tc = tinycolor({ r, g, b });

          // Ensure the color is vibrant enough
          if (tc.toHsl().s < 0.3) {
            tc.saturate(30);
          }

          // Apply brightness adjustment if specified
          if (brightness !== undefined) {
            tc.brighten(brightness);
          }

          // Apply opacity if specified
          if (opacity !== undefined) {
            tc.setAlpha(opacity);
            setColor(tc.toRgbString());
          } else {
            setColor(tc.toHexString());
          }

          setIsLoading(false);
        };

        img.onerror = () => {
          setIsLoading(false);
        };

        img.src = imageUrl;
      } catch (error) {
        console.error("Error extracting color:", error);
        setIsLoading(false);
      }
    };

    extractColor();
  }, [imageUrl, brightness, opacity]);

  return { color, isLoading };
};
