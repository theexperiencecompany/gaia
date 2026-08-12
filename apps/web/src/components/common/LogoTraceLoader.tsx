"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * GAIA logo mark — viewBox of the source brand SVG. The logo is a pinwheel of
 * three spiral arms around an empty center, with comma-shaped gaps between
 * the arms. Each arm is built from three overlapping color crescents:
 *
 *   - the arm backbone (mid blue,   #059cda)
 *   - a partial crescent (dark blue, #0f537c)
 *   - a partial crescent (bright,    #02bdff)
 *
 * rendered in that order (later layers paint over earlier ones). The loader
 * traces each color's region contour separately, in its own color, and the
 * fill fades in per color, so the resolved mark matches the brand asset.
 */
const LOGO_VIEW_BOX = "0 0 2441.45 2400";

/**
 * One color layer of the logo: the visible boundary of that color's region —
 * the union of its filled shapes minus the regions drawn over it (later
 * layers paint over earlier ones in the source), so the traced outlines abut
 * cleanly instead of crossing where layers overlap. One closed subpath per
 * arm. Plus that color's original filled paths, verbatim.
 */
type LogoLayer = {
  color: string;
  tracePath: string;
  fillPaths: readonly string[];
};

const LOGO_LAYERS = [
  {
    // cls-3 — #059cda
    color: "#059cda",
    tracePath:
      "M2294.8,754.9L2323.0,808.0L2335.7,851.2L2344.4,906.9L2347.9,970.2L2345.3,1034.8L2336.7,1099.1L2322.3,1161.2L2307.9,1205.5L2282.2,1261.8L2242.9,1321.7L2194.5,1377.1L2139.1,1427.7L2078.5,1473.1L1993.3,1525.3L1907.2,1567.0L1872.3,1581.0L1856.3,1584.0L1871.7,1744.9L1871.7,1803.4L1866.9,1867.5L1850.5,1958.0L1833.5,2014.5L1811.4,2067.8L1784.4,2117.9L1734.4,2186.5L1694.7,2227.9L1649.9,2265.7L1600.0,2299.7L1544.8,2330.0L1462.0,2364.4L1407.1,2377.2L1356.8,2378.2L1400.6,2392.0L1439.8,2398.3L1536.3,2381.8L1620.3,2358.6L1701.5,2328.9L1779.6,2293.0L1854.3,2251.2L1925.6,2203.9L1993.1,2151.4L2056.6,2094.2L2115.9,2032.5L2170.8,1966.9L2221.1,1897.5L2266.6,1824.8L2307.0,1749.1L2342.2,1670.9L2371.9,1590.4L2395.8,1508.1L2413.8,1424.2L2425.7,1339.2L2431.2,1253.4L2430.2,1167.2L2422.3,1081.0L2407.4,995.1L2385.3,909.8L2367.0,856.0L2346.9,814.4L2324.4,783.0L2294.8,754.9ZM118.9,785.0L94.9,821.1L77.0,860.1L40.4,983.8L25.0,1066.7L16.1,1150.0L13.7,1233.2L17.5,1316.2L27.3,1398.5L43.0,1479.9L64.2,1560.0L90.9,1638.4L122.9,1714.9L159.9,1789.1L201.7,1860.7L248.1,1929.4L299.0,1994.8L354.2,2056.6L413.4,2114.4L476.4,2168.0L543.1,2217.1L613.3,2261.2L686.7,2300.0L763.1,2333.3L842.5,2360.7L924.5,2381.9L971.3,2390.6L1011.6,2393.7L1044.9,2390.6L1077.6,2380.4L1035.7,2378.0L969.2,2361.2L923.7,2342.5L855.9,2305.0L791.2,2259.0L732.7,2207.0L683.2,2151.9L656.8,2114.9L628.2,2059.9L607.0,2001.9L591.1,1941.2L580.3,1878.8L574.1,1815.3L572.5,1730.6L577.7,1647.5L582.7,1606.2L589.0,1586.2L586.8,1581.8L527.4,1560.1L441.1,1516.9L356.8,1464.0L298.2,1418.4L244.9,1367.3L198.4,1310.6L159.8,1247.9L139.1,1202.7L122.8,1154.6L109.2,1092.1L100.9,1019.4L99.2,961.9L102.3,904.6L111.0,850.0L126.1,800.7L148.3,759.3L118.9,785.0ZM303.6,489.5L323.1,464.5L361.4,428.3L407.8,394.6L458.7,364.1L511.0,337.9L577.1,310.9L619.5,297.8L665.6,288.4L734.0,282.7L801.4,286.1L867.6,297.7L932.4,316.5L995.6,341.7L1077.2,383.4L1164.5,438.8L1221.5,486.5L1228.1,486.5L1263.0,455.4L1327.3,411.4L1385.9,377.1L1462.2,339.4L1537.6,311.0L1587.6,297.5L1662.5,285.8L1712.6,283.9L1788.3,290.4L1839.3,301.3L1917.0,327.7L1969.8,352.3L2026.5,385.0L2080.4,424.5L2127.8,470.9L2159.5,514.9L2148.4,475.0L2129.5,438.1L2099.8,397.4L2060.6,354.2L2000.5,296.8L1936.4,244.6L1868.8,197.8L1798.0,156.2L1724.4,120.0L1648.4,89.0L1570.4,63.4L1490.8,43.1L1409.9,28.1L1328.2,18.5L1246.0,14.2L1163.7,15.3L1081.7,21.7L1000.4,33.5L920.2,50.6L841.4,73.1L764.5,101.0L689.8,134.3L617.7,173.0L548.6,217.1L482.9,266.6L420.9,321.5L363.2,381.8L321.4,434.4L299.6,475.7L290.1,514.9L303.6,489.5Z",
    fillPaths: [
      "M2294.76,754.91c52.05,40.47,71.76,93.13,90.55,154.88,197.81,650.16-261.39,1391.76-935.7,1488.14-21.8,3.12-71.79-10.84-92.82-19.75,56.56,5.45,107.78-12.37,158.53-34.53,231.32-101.03,347.34-289.02,356.36-540.29,2.82-78.64-6.26-139.1-15.36-215-.17-1.41.2-2.97,0-4.36,10.57.02,20.27-4.54,29.83-8.35,160.58-63.98,349.04-190.78,416.22-356.05,43.56-107.16,57.02-244.62,35.39-358.23-7.47-39.21-20.03-73.69-42.99-106.46Z",
      "M148.33,759.27c-66.61,93.84-55.47,288.96-25.54,395.37,53.37,189.75,213.09,315.21,384.68,396.32,24.67,11.66,53.12,24.23,79.31,30.86l2.18,4.36c-1.66,6.59-5.46,14.39-6.37,20.9-21.41,152.78-12.44,330.19,53.98,471.49,64.34,136.89,285.66,307.41,441.01,301.8-49.61,22.02-102.16,12.47-153.1,1.5C286.1,2244.42-134.68,1528.46,62.69,901.61c14.68-46.61,31.08-89.68,64.6-126.3l21.04-16.04Z",
      "M290.12,514.91c5.34-52.72,39.4-94.96,73.04-133.12,426.06-483.19,1252.51-488.16,1697.43-27.57,43.5,45.03,89.12,97.14,98.92,160.69-42.11-71.19-117.1-125.07-189.73-162.59-204.09-105.44-387.41-82.71-583.93,24.76-47.65,26.06-104.22,61.67-145.71,96.44-4.4,3.69-8.87,8.24-12.06,13.03h-6.54c-29.89-30.53-68.56-56.62-104.89-79.45-149.66-94.07-319.77-154.18-497.17-109.29-97.33,24.63-290.5,119.22-329.37,217.1ZM547.52,233.44c1.45,1.35,8.65-1.02,8.67-3.26.06-6.51-12.83-.61-8.67,3.26Z",
    ],
  },
  {
    // cls-1 — #0f537c
    color: "#0f537c",
    tracePath:
      "M1856.3,1584.0L1907.2,1567.0L1993.3,1525.3L2057.5,1487.1L2119.4,1443.4L2176.7,1394.5L2227.7,1340.7L2270.2,1282.3L2292.9,1240.9L2317.9,1176.2L2336.7,1099.1L2346.5,1018.6L2347.6,954.2L2340.4,876.3L2326.3,817.3L2313.0,785.4L2294.8,754.9L2273.3,741.0L2240.5,729.2L2196.5,728.2L2153.7,740.9L2113.5,763.9L2077.4,794.0L2043.7,831.6L2010.6,877.5L1967.3,954.8L1942.4,1010.7L1910.9,1099.0L1886.3,1190.4L1868.4,1281.9L1857.0,1370.7L1851.9,1454.1L1853.0,1551.1L1856.3,1584.0ZM588.5,1587.9L580.0,1627.1L572.5,1730.6L574.1,1815.3L583.4,1899.7L601.1,1981.9L620.5,2040.9L645.8,2096.6L669.3,2133.4L715.0,2188.8L770.8,2242.1L833.8,2290.5L900.9,2331.1L969.2,2361.2L1035.7,2378.0L1079.8,2380.3L1116.5,2364.4L1142.0,2339.7L1163.1,2301.3L1173.1,2259.6L1172.5,2215.2L1165.4,2176.3L1145.2,2116.5L1115.8,2056.5L1079.9,1998.1L1039.9,1942.8L985.0,1877.0L932.5,1822.6L861.9,1759.3L786.2,1700.8L722.6,1658.1L639.9,1610.9L588.5,1587.9ZM1221.5,486.6L1164.5,438.8L1097.0,395.0L1016.3,351.3L953.6,324.3L889.3,303.2L823.6,289.1L756.6,282.8L711.3,283.5L642.6,292.5L577.1,310.9L493.7,346.1L424.4,384.0L361.4,428.3L312.7,476.9L290.1,514.9L285.6,532.3L285.1,550.6L293.9,587.6L316.3,626.4L347.9,655.7L382.6,675.4L421.9,689.8L487.4,702.9L557.8,707.2L629.9,704.4L700.3,696.3L785.8,680.4L859.5,661.2L950.5,630.6L1039.6,592.9L1125.3,548.5L1221.5,486.6Z",
    fillPaths: [
      "M1856.31,1584c-5.67-40.19-5.48-89.09-4.45-129.91,5.15-203.81,70.21-488.23,209.55-643.49,58.33-65,152.18-118.81,233.35-55.69,22.96,32.77,35.52,67.24,42.99,106.46,21.63,113.62,8.17,251.08-35.39,358.23-67.18,165.27-255.63,292.07-416.22,356.05-9.56,3.81-19.26,8.37-29.83,8.35Z",
      "M588.96,1586.18c131.16,59.49,255.06,148.11,356.9,249.61,95.16,94.85,235.97,275.99,227.8,417.03-3,51.75-34.83,114.47-89.54,125.35-1.76.35-3.74-.05-4.36,2.18-.72.06-1.46-.03-2.18,0-155.36,5.62-376.67-164.91-441.01-301.8-66.41-141.3-75.38-318.71-53.98-471.49.91-6.51,4.71-14.31,6.37-20.9Z",
      "M1221.55,486.55c-117.35,84.94-258.36,147.92-398.71,184.83-132.56,34.87-378.72,69.78-490.24-27.69-32.68-28.56-59.45-86.04-42.48-128.78,38.87-97.88,232.04-192.47,329.37-217.1,177.4-44.9,347.51,15.22,497.17,109.29,36.33,22.84,75,48.92,104.89,79.45Z",
    ],
  },
  {
    // cls-2 — #02bdff
    color: "#02bdff",
    tracePath:
      "M1856.3,1588.4L1808.6,1609.3L1734.8,1651.2L1660.6,1700.9L1587.7,1757.2L1518.1,1819.1L1453.3,1885.5L1395.3,1955.5L1361.3,2003.6L1331.6,2052.4L1300.1,2117.5L1280.7,2176.3L1272.7,2221.6L1272.7,2265.7L1282.7,2306.5L1304.8,2342.2L1327.3,2362.1L1356.8,2378.2L1414.1,2376.2L1468.7,2362.1L1544.8,2330.0L1600.0,2299.7L1673.0,2247.2L1715.2,2207.7L1769.0,2141.6L1798.5,2093.3L1823.1,2041.6L1842.6,1986.7L1862.7,1898.4L1869.9,1835.8L1871.7,1744.9L1856.3,1588.4ZM151.1,753.3L120.3,816.4L107.5,867.7L100.7,923.5L99.8,1000.4L106.5,1074.6L119.0,1140.3L139.1,1202.7L159.8,1247.9L184.6,1290.4L228.6,1349.0L262.0,1384.9L317.2,1434.2L377.3,1478.1L441.1,1516.9L527.4,1560.1L586.8,1581.8L591.9,1506.9L590.8,1416.2L582.8,1325.8L568.7,1236.6L548.2,1149.1L517.2,1051.2L487.0,976.3L450.9,904.7L409.0,840.0L377.8,802.7L344.0,771.4L293.5,740.2L252.0,728.0L231.6,726.7L204.7,729.9L177.9,738.8L151.1,753.3ZM2159.5,514.9L2127.8,470.9L2080.4,424.5L2026.5,385.0L1969.8,352.3L1917.0,327.7L1839.3,301.3L1788.3,290.4L1712.6,283.9L1662.5,285.8L1587.6,297.5L1537.6,311.0L1462.2,339.4L1385.9,377.1L1327.3,411.4L1263.0,455.4L1228.1,486.5L1287.8,527.0L1363.7,570.2L1442.8,607.7L1523.6,639.3L1618.1,668.9L1698.2,688.0L1780.2,701.3L1862.2,707.4L1942.3,704.8L2006.9,694.5L2056.5,679.0L2100.2,655.8L2134.6,623.8L2152.2,593.5L2161.0,557.4L2159.5,514.9Z",
    fillPaths: [
      "M1856.31,1588.36c9.1,75.9,18.18,136.36,15.36,215-9.02,251.27-125.04,439.26-356.36,540.29-50.75,22.16-101.96,39.98-158.53,34.53-126.94-53.77-87.47-203.8-38.27-301.19,95.44-188.97,303.5-371.35,490.07-467.64,15.29-7.89,31.28-16.21,47.73-20.99Z",
      "M148.33,759.27c1.09-1.54,1.16-4.77,2.73-5.94,51.61-33.19,101.95-35.59,156.6-6.16,144.17,77.63,232.06,337.61,261.03,489.46,21.52,112.79,30.38,230.97,18.09,345.18-26.19-6.63-54.64-19.2-79.31-30.86-171.59-81.11-331.31-206.57-384.68-396.32-29.93-106.41-41.07-301.52,25.54-395.37Z",
      "M2159.52,514.91c18.04,116.94-78.85,167.98-178.46,184.77-146.36,24.67-319.01-11.4-457.43-60.36-103.63-36.66-207.05-87.74-295.53-152.77,3.19-4.79,7.66-9.34,12.06-13.03,41.49-34.77,98.06-70.38,145.71-96.44,196.52-107.47,379.84-130.2,583.93-24.76,72.63,37.52,147.62,91.41,189.73,162.59Z",
    ],
  },
] as const;

/** How long one full draw cycle takes: the nine arm outlines draw in
 *  sequence over 3×loopDurationSeconds (one color layer per lap), which is
 *  90% of the cycle; the remaining 10% is the fade-out reset. */
const DRAW_CYCLE_FRACTION = 0.9;

/** The trace route, flattened into one entry per arm outline (3 per layer),
 *  in draw order: mid-blue backbones first, then dark, then bright. */
const TRACE_SUBPATHS = LOGO_LAYERS.flatMap((layer) =>
  layer.tracePath.match(/M[^Z]*Z/g)!.map((subpath) => ({ layer, subpath })),
);

/** How long the outline takes to expand from its drawn state to the full outline. */
const OUTLINE_CLOSE_MS = 600;

/**
 * Internal animation state machine:
 * - "loop": short stroke segments sweep the layers' trace paths (loading)
 * - "closingOutline": each layer's dash expands until its full outline is drawn
 * - "fadingFill": each layer's filled paths fade in over its closed outline
 * - "done": the resolved filled logo (terminal state)
 */
type LoaderPhase = "loop" | "closingOutline" | "fadingFill" | "done";

export type LogoTraceLoaderProps = {
  /** While true, the trace loops. Becomes false (or `isComplete` true) to resolve. Default: true. */
  loading?: boolean;
  /** Force-resolve immediately, even while `loading` is still true. */
  isComplete?: boolean;
  /** Rendered box size in px. The SVG box is fixed from first render (no layout shift). */
  size?: number;
  /** Stroke width in viewBox units (the viewBox is 2441 × 2400). Default: 28 (~1.1px at 96px). */
  strokeWidth?: number;
  /** Seconds per color layer's drawing lap — the nine arm outlines draw in
   *  sequence (one layer of three arms per lap). The full draw cycle takes
   *  ~3.7× this (drawing + the fade-out reset). Default: 2.4. */
  loopDurationSeconds?: number;
  /** Seconds for the fill to fade in after the outline closes. Default: 0.5. */
  fillFadeSeconds?: number;
  /**
   * Render every layer in `currentColor` (single-color silhouette, stylable
   * via className) instead of the logo's brand colors. Default: false.
   */
  monochrome?: boolean;
  /** Passed to the svg element; color via `currentColor` when `monochrome`. */
  className?: string;
  /** Accessible label for the status region. Default: "Loading". */
  ariaLabel?: string;
  /** Called exactly once, when the filled logo is visible. */
  onDone?: () => void;
};

/**
 * Traces the GAIA logo mark while work is in progress, then resolves into the
 * filled logo when loading completes.
 *
 * The logo's three color layers (the arm backbones, the dark crescents, and
 * the bright crescents) are traced separately, each along the exact outer
 * contour of that color's region — one closed subpath per arm, since browsers
 * dash each subpath independently, the loop shows synchronized segments
 * sweeping every arm of every layer. When resolving, each layer's dash
 * expands to its full outline, then its filled paths fade in over it, in the
 * same z-order as the source asset, so the resolved mark matches the brand
 * logo exactly.
 *
 * All transitions are driven by timeouts (not SVG/CSS animation events), so
 * the phase machine advances even if animations are throttled. With
 * `prefers-reduced-motion`, the filled logo is shown immediately and `onDone`
 * still fires.
 */
export default function LogoTraceLoader({
  loading = true,
  isComplete = false,
  size = 96,
  strokeWidth = 28,
  loopDurationSeconds = 2.4,
  fillFadeSeconds = 0.5,
  monochrome = false,
  className,
  ariaLabel = "Loading",
  onDone,
}: LogoTraceLoaderProps) {
  // The nine arm outlines draw in sequence over 3×loopDurationSeconds
  // (one color layer per lap); that drawing occupies 90% of the cycle, the
  // rest is the fade-out reset.
  const drawCycleSeconds = (3 * loopDurationSeconds) / DRAW_CYCLE_FRACTION;
  // Read synchronously so the first paint already shows the resolved logo
  // under prefers-reduced-motion (no loop flash before effects run).
  const [reducedMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ??
        false),
  );
  const [phase, setPhase] = useState<LoaderPhase>(
    reducedMotion ? "done" : "loop",
  );
  const onDoneRef = useRef(onDone);
  const doneFiredRef = useRef(false);

  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  // React to OS-level reduced-motion changes: resolve immediately.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setPhase("done");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Phase machine. Timeout-driven so nothing depends on animation callbacks.
  useEffect(() => {
    if (phase === "loop") {
      if (isComplete || !loading) setPhase("closingOutline");
    } else if (phase === "closingOutline") {
      const t = setTimeout(() => setPhase("fadingFill"), OUTLINE_CLOSE_MS + 50);
      return () => clearTimeout(t);
    } else if (phase === "fadingFill") {
      const t = setTimeout(() => setPhase("done"), fillFadeSeconds * 1000 + 50);
      return () => clearTimeout(t);
    }
    return;
  }, [phase, isComplete, loading, fillFadeSeconds]);

  // Call onDone exactly once, once the filled logo is visible.
  useEffect(() => {
    if (phase !== "done" || doneFiredRef.current) return;
    doneFiredRef.current = true;
    onDoneRef.current?.();
  }, [phase]);

  const layerColor = (layer: LogoLayer) =>
    monochrome ? "currentColor" : layer.color;

  return (
    <svg
      role="status"
      aria-label={ariaLabel}
      viewBox={LOGO_VIEW_BOX}
      width={size}
      height={size}
      className={cn("shrink-0", className)}
    >
      {/* The animated trace: one seamless drawing animation — each arm's
          outline draws itself progressively, in order (mid-blue backbones →
          dark → bright), and the next arm starts drawing the moment the
          previous one finishes, so the logo builds up shape by shape with no
          gaps. The group fades out briefly at the end of the cycle, then the
          next cycle redraws from the first arm. On resolve, every element's
          dash expands to its full outline. */}
      {phase === "loop" || phase === "closingOutline" ? (
        <g
          style={
            phase === "loop"
              ? {
                  animation: `logo-trace-loader-cycle ${drawCycleSeconds}s linear infinite`,
                }
              : {
                  animation: "none",
                  opacity: 1,
                  transition: `opacity ${OUTLINE_CLOSE_MS}ms ease-out`,
                }
          }
        >
          {TRACE_SUBPATHS.map(({ layer, subpath }, drawIndex) => (
            <path
              key={`${layer.color}:${subpath.slice(0, 16)}`}
              d={subpath}
              fill="none"
              stroke={layerColor(layer)}
              strokeWidth={strokeWidth}
              strokeLinecap="round"
              strokeLinejoin="round"
              pathLength={1}
              style={
                phase === "loop"
                  ? {
                      // Each arm draws during its own 10%-of-cycle window,
                      // staggered in draw order — the previous arm finishes
                      // right as the next one starts.
                      animation: `logo-trace-loader-draw-${drawIndex} ${drawCycleSeconds}s linear infinite`,
                      strokeDasharray: "0 1",
                    }
                  : {
                      animation: "none",
                      strokeDasharray: "1 0",
                      transition: `stroke-dasharray ${OUTLINE_CLOSE_MS}ms ease-out`,
                    }
              }
            />
          ))}
        </g>
      ) : null}

      {/* The filled logo: each layer's original paths fade in over its closed
          outline, in the source z-order (backbones first, then dark, then
          bright), so the resolved mark matches the brand asset exactly. */}
      {phase === "fadingFill" || phase === "done" ? (
        <g
          style={
            phase === "fadingFill"
              ? {
                  animation: `logo-trace-loader-fill-in ${fillFadeSeconds}s ease-out both`,
                }
              : undefined
          }
        >
          {LOGO_LAYERS.map((layer) =>
            layer.fillPaths.map((path) => (
              <path key={path} d={path} fill={layerColor(layer)} />
            )),
          )}
        </g>
      ) : null}
    </svg>
  );
}
