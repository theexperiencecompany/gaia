"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * GAIA logo mark — viewBox of the source brand SVG. The logo is a pinwheel of
 * three spiral arms (each built from three overlapping color layers) around an
 * empty center, with comma-shaped gaps between the arms.
 */
const LOGO_VIEW_BOX = "0 0 2441.45 2400";

/**
 * The route followed by the animated stroke: the exact outer contour of the
 * union of the logo's filled shapes, as three closed subpaths (one per arm).
 * Derived from the source SVG (no transforms in the file); the micro-gap
 * between the right arm and its detached middle layer was snapped shut so the
 * arm reads as one loop. The center hole and comma gaps are faithfully absent
 * — they are negative space, revealed by the fill.
 */
const TRACE_PATH =
  "M1356.8,2378.2L1400.6,2392.0L1439.8,2398.3L1536.3,2381.8L1620.3,2358.6L1701.5,2328.9L1779.6,2293.0L1854.3,2251.2L1925.6,2203.9L1993.1,2151.4L2056.6,2094.2L2115.9,2032.5L2170.8,1966.9L2221.1,1897.5L2266.6,1824.8L2307.0,1749.1L2342.2,1670.9L2371.9,1590.4L2395.8,1508.1L2413.8,1424.2L2425.7,1339.2L2431.2,1253.4L2430.2,1167.2L2422.3,1081.0L2407.4,995.0L2382.9,901.8L2360.9,841.7L2338.7,801.4L2307.6,765.7L2273.3,741.0L2240.5,729.2L2196.5,728.2L2153.7,740.9L2113.5,763.9L2077.4,794.0L2043.7,831.6L2010.6,877.5L1967.3,954.8L1942.4,1010.7L1910.9,1099.0L1893.7,1159.8L1873.6,1251.5L1860.1,1341.5L1852.9,1427.1L1851.5,1516.4L1856.3,1588.3L1784.1,1622.4L1710.0,1667.0L1636.0,1718.9L1564.1,1777.2L1495.8,1840.8L1433.2,1908.5L1377.8,1979.4L1331.6,2052.4L1306.0,2103.5L1284.8,2161.3L1272.7,2221.6L1272.7,2265.7L1282.7,2306.5L1296.0,2331.0L1327.3,2362.1L1356.8,2378.2ZM148.3,759.3L118.9,785.0L89.3,832.0L64.6,895.6L40.4,983.8L25.0,1066.7L16.1,1150.0L13.7,1233.2L17.5,1316.2L27.3,1398.5L43.0,1479.9L64.2,1560.0L90.9,1638.4L122.9,1714.9L159.9,1789.1L201.7,1860.7L248.1,1929.4L299.0,1994.8L354.2,2056.6L413.4,2114.4L476.4,2168.0L543.1,2217.1L613.3,2261.2L686.7,2300.0L763.1,2333.3L842.5,2360.7L924.5,2381.9L984.7,2392.3L1024.9,2393.2L1058.0,2387.4L1110.6,2368.1L1127.5,2355.6L1142.0,2339.7L1163.1,2301.3L1173.1,2259.6L1172.5,2215.2L1165.4,2176.3L1145.2,2116.5L1115.8,2056.5L1079.9,1998.1L1039.9,1942.8L985.0,1877.0L932.5,1822.6L861.9,1759.3L801.7,1712.0L738.7,1668.4L656.7,1619.8L589.0,1586.2L586.8,1581.8L592.2,1491.8L590.0,1401.1L580.8,1310.9L564.6,1216.2L541.5,1125.3L507.8,1026.1L475.6,951.9L437.6,882.1L393.7,820.7L361.2,786.2L326.1,758.3L293.5,740.2L258.8,729.1L218.1,727.6L177.9,738.8L151.1,753.3L148.3,759.3ZM288.2,520.6L285.7,556.8L296.4,593.6L320.2,631.1L347.9,655.7L382.6,675.4L443.0,695.3L487.4,702.9L557.8,707.2L629.9,704.4L722.8,692.8L804.9,675.9L896.0,649.8L986.4,616.3L1074.4,575.9L1158.3,528.9L1221.6,486.6L1228.1,486.6L1300.1,534.6L1376.7,576.9L1442.8,607.7L1523.6,639.3L1598.6,663.4L1677.9,683.7L1759.6,698.6L1841.8,706.7L1922.6,706.3L1981.1,699.7L2032.2,687.6L2079.3,668.4L2118.8,640.9L2141.4,614.3L2156.1,582.2L2161.7,543.9L2156.2,498.6L2141.7,459.9L2115.4,417.3L2072.0,366.1L2000.5,296.8L1936.4,244.6L1868.8,197.8L1798.0,156.2L1724.4,120.0L1648.4,89.0L1570.4,63.4L1490.8,43.1L1409.9,28.1L1328.2,18.5L1246.0,14.2L1163.7,15.3L1081.7,21.7L1000.4,33.5L920.2,50.6L841.4,73.1L764.5,101.0L689.8,134.3L617.7,173.0L548.6,217.1L482.9,266.6L420.9,321.5L363.2,381.8L321.4,434.4L299.6,475.7L288.2,520.6Z";

/**
 * The filled logo mark — the source SVG's original path data, verbatim, so
 * the resolved logo matches the brand asset exactly (including its compound
 * subpaths and negative space). Rendered in `currentColor`.
 */
const FILL_PATHS = [
  "M2294.76,754.91c52.05,40.47,71.76,93.13,90.55,154.88,197.81,650.16-261.39,1391.76-935.7,1488.14-21.8,3.12-71.79-10.84-92.82-19.75,56.56,5.45,107.78-12.37,158.53-34.53,231.32-101.03,347.34-289.02,356.36-540.29,2.82-78.64-6.26-139.1-15.36-215-.17-1.41.2-2.97,0-4.36,10.57.02,20.27-4.54,29.83-8.35,160.58-63.98,349.04-190.78,416.22-356.05,43.56-107.16,57.02-244.62,35.39-358.23-7.47-39.21-20.03-73.69-42.99-106.46Z",
  "M148.33,759.27c-66.61,93.84-55.47,288.96-25.54,395.37,53.37,189.75,213.09,315.21,384.68,396.32,24.67,11.66,53.12,24.23,79.31,30.86l2.18,4.36c-1.66,6.59-5.46,14.39-6.37,20.9-21.41,152.78-12.44,330.19,53.98,471.49,64.34,136.89,285.66,307.41,441.01,301.8-49.61,22.02-102.16,12.47-153.1,1.5C286.1,2244.42-134.68,1528.46,62.69,901.61c14.68-46.61,31.08-89.68,64.6-126.3l21.04-16.04Z",
  "M290.12,514.91c5.34-52.72,39.4-94.96,73.04-133.12,426.06-483.19,1252.51-488.16,1697.43-27.57,43.5,45.03,89.12,97.14,98.92,160.69-42.11-71.19-117.1-125.07-189.73-162.59-204.09-105.44-387.41-82.71-583.93,24.76-47.65,26.06-104.22,61.67-145.71,96.44-4.4,3.69-8.87,8.24-12.06,13.03h-6.54c-29.89-30.53-68.56-56.62-104.89-79.45-149.66-94.07-319.77-154.18-497.17-109.29-97.33,24.63-290.5,119.22-329.37,217.1ZM547.52,233.44c1.45,1.35,8.65-1.02,8.67-3.26.06-6.51-12.83-.61-8.67,3.26Z",
  "M1856.31,1584c-5.67-40.19-5.48-89.09-4.45-129.91,5.15-203.81,70.21-488.23,209.55-643.49,58.33-65,152.18-118.81,233.35-55.69,22.96,32.77,35.52,67.24,42.99,106.46,21.63,113.62,8.17,251.08-35.39,358.23-67.18,165.27-255.63,292.07-416.22,356.05-9.56,3.81-19.26,8.37-29.83,8.35Z",
  "M588.96,1586.18c131.16,59.49,255.06,148.11,356.9,249.61,95.16,94.85,235.97,275.99,227.8,417.03-3,51.75-34.83,114.47-89.54,125.35-1.76.35-3.74-.05-4.36,2.18-.72.06-1.46-.03-2.18,0-155.36,5.62-376.67-164.91-441.01-301.8-66.41-141.3-75.38-318.71-53.98-471.49.91-6.51,4.71-14.31,6.37-20.9Z",
  "M1221.55,486.55c-117.35,84.94-258.36,147.92-398.71,184.83-132.56,34.87-378.72,69.78-490.24-27.69-32.68-28.56-59.45-86.04-42.48-128.78,38.87-97.88,232.04-192.47,329.37-217.1,177.4-44.9,347.51,15.22,497.17,109.29,36.33,22.84,75,48.92,104.89,79.45Z",
  "M1856.31,1588.36c9.1,75.9,18.18,136.36,15.36,215-9.02,251.27-125.04,439.26-356.36,540.29-50.75,22.16-101.96,39.98-158.53,34.53-126.94-53.77-87.47-203.8-38.27-301.19,95.44-188.97,303.5-371.35,490.07-467.64,15.29-7.89,31.28-16.21,47.73-20.99Z",
  "M148.33,759.27c1.09-1.54,1.16-4.77,2.73-5.94,51.61-33.19,101.95-35.59,156.6-6.16,144.17,77.63,232.06,337.61,261.03,489.46,21.52,112.79,30.38,230.97,18.09,345.18-26.19-6.63-54.64-19.2-79.31-30.86-171.59-81.11-331.31-206.57-384.68-396.32-29.93-106.41-41.07-301.52,25.54-395.37Z",
  "M2159.52,514.91c18.04,116.94-78.85,167.98-178.46,184.77-146.36,24.67-319.01-11.4-457.43-60.36-103.63-36.66-207.05-87.74-295.53-152.77,3.19-4.79,7.66-9.34,12.06-13.03,41.49-34.77,98.06-70.38,145.71-96.44,196.52-107.47,379.84-130.2,583.93-24.76,72.63,37.52,147.62,91.41,189.73,162.59Z",
] as const;

/** How long the outline takes to sweep from the looping dash to a full outline. */
const OUTLINE_CLOSE_MS = 600;

/**
 * Internal animation state machine:
 * - "loop": a short stroke segment sweeps the trace path (loading in progress)
 * - "closingOutline": the dash expands until the full outline is drawn
 * - "fadingFill": the filled logo fades in over the closed outline
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
  /** Seconds per full sweep of the trace loop. Default: 2.4. */
  loopDurationSeconds?: number;
  /** Seconds for the fill to fade in after the outline closes. Default: 0.5. */
  fillFadeSeconds?: number;
  /** Passed to the svg element; color via `currentColor` (e.g. `text-zinc-100`). */
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
 * The trace path is the exact outer contour of the logo's three pinwheel arms
 * (one closed subpath per arm — browsers dash each subpath independently, so
 * the loop shows three synchronized segments sweeping the arms). When
 * resolving, the dash expands to the full outline, then the original filled
 * paths fade in over it.
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
  className,
  ariaLabel = "Loading",
  onDone,
}: LogoTraceLoaderProps) {
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

  return (
    <svg
      role="status"
      aria-label={ariaLabel}
      viewBox={LOGO_VIEW_BOX}
      width={size}
      height={size}
      className={cn("shrink-0", className)}
    >
      {/* Static underlay: the full outline at low emphasis, so the mark reads
          even before the trace segment passes. */}
      <g opacity="0.18">
        <path
          d={TRACE_PATH}
          fill="none"
          stroke="currentColor"
          strokeWidth={Math.max(1, strokeWidth / 2)}
          strokeLinejoin="round"
        />
      </g>

      {/* The animated trace: a short dash sweeping the arms. On resolve, the
          dash expands to the full outline while the sweep keeps running, so
          the close is seamless (no dash-phase jump). pathLength normalizes
          the dash units; each subpath dashes independently. */}
      {phase === "loop" || phase === "closingOutline" ? (
        <path
          d={TRACE_PATH}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          style={
            phase === "loop"
              ? {
                  animation: `logo-trace-loader-loop ${loopDurationSeconds}s linear infinite`,
                  strokeDasharray: "0.16 0.84",
                }
              : {
                  animation: `logo-trace-loader-loop ${loopDurationSeconds}s linear infinite`,
                  strokeDasharray: "1 0",
                  transition: `stroke-dasharray ${OUTLINE_CLOSE_MS}ms ease-out`,
                }
          }
        />
      ) : null}

      {/* The filled logo, faded in over the closed outline. */}
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
          {FILL_PATHS.map((path) => (
            <path key={path} d={path} fill="currentColor" />
          ))}
        </g>
      ) : null}
    </svg>
  );
}
