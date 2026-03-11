/**
 * Custom JSX runtime shim for @theexperiencecompany/gaia-icons on React Native.
 *
 * Metro redirects `react/jsx-runtime` imports that originate from within the
 * gaia-icons package to this file (see metro.config.js resolveRequest).
 *
 * This maps lowercase SVG element names ("svg", "path", …) to their
 * react-native-svg equivalents so the gaia-icons components render correctly
 * without any code-generation step.
 */

import { jsx as _jsx, jsxs as _jsxs, Fragment } from "react/jsx-runtime";
import Svg, {
  Circle,
  ClipPath,
  Defs,
  Ellipse,
  G,
  Line,
  LinearGradient,
  Mask,
  Path,
  Polygon,
  Polyline,
  RadialGradient,
  Rect,
  Stop,
  Symbol as SvgSymbol,
  Text,
  TSpan,
  Use,
} from "react-native-svg";

const SVG_ELEMENT_MAP: Record<string, unknown> = {
  svg: Svg,
  path: Path,
  circle: Circle,
  rect: Rect,
  line: Line,
  polyline: Polyline,
  polygon: Polygon,
  ellipse: Ellipse,
  g: G,
  defs: Defs,
  clipPath: ClipPath,
  linearGradient: LinearGradient,
  radialGradient: RadialGradient,
  stop: Stop,
  mask: Mask,
  use: Use,
  symbol: SvgSymbol,
  text: Text,
  tspan: TSpan,
};

function resolveType(type: unknown): unknown {
  if (typeof type === "string") return SVG_ELEMENT_MAP[type] ?? type;
  return type;
}

// Strip web-only props that React Native SVG doesn't accept
function cleanProps(
  type: unknown,
  props: Record<string, unknown>,
): Record<string, unknown> {
  if (type !== Svg) return props;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { xmlns, className, ...rest } = props as {
    xmlns?: unknown;
    className?: unknown;
    [key: string]: unknown;
  };
  return rest;
}

export function jsx(
  type: unknown,
  props: Record<string, unknown>,
  key?: unknown,
): unknown {
  const t = resolveType(type);
  return _jsx(t as never, cleanProps(t, props) as never, key as never);
}

export function jsxs(
  type: unknown,
  props: Record<string, unknown>,
  key?: unknown,
): unknown {
  const t = resolveType(type);
  return _jsxs(t as never, cleanProps(t, props) as never, key as never);
}

export { Fragment };
