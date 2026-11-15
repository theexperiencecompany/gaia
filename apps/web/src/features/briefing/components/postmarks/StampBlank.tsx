/** The stamp art's canvas, so a blank has a collected stamp's proportions. */
const STAMP_WIDTH = 600;
const STAMP_HEIGHT = 850;
/**
 * Distance between perforation holes, and each hole's radius, in stamp units:
 * coarse, so the holes still read on a blank a dozen pixels wide.
 */
const PERFORATION_PITCH = 150;
const PERFORATION_RADIUS = 40;

type Point = [number, number];

/**
 * A rectangle traced clockwise whose every edge is bitten by a row of
 * half-circle perforations, the outline of a stamp torn from its sheet.
 */
function perforatedOutline(width: number, height: number): string {
  const corners: Point[] = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ];
  const segments = corners.map(([fromX, fromY], index) => {
    const [toX, toY] = corners[(index + 1) % corners.length];
    const length = Math.hypot(toX - fromX, toY - fromY);
    const holes = Math.round(length / PERFORATION_PITCH);
    const stepX = (toX - fromX) / length;
    const stepY = (toY - fromY) / length;
    const bites = Array.from({ length: holes }, (_, hole) => {
      const along = (length / holes) * (hole + 0.5);
      const start = along - PERFORATION_RADIUS;
      const end = along + PERFORATION_RADIUS;
      return [
        `L ${fromX + stepX * start} ${fromY + stepY * start}`,
        // Sweep 0 on a clockwise trace bends each half-circle into the stamp.
        `A ${PERFORATION_RADIUS} ${PERFORATION_RADIUS} 0 0 0 ${fromX + stepX * end} ${fromY + stepY * end}`,
      ].join(" ");
    });
    return [...bites, `L ${toX} ${toY}`].join(" ");
  });
  return `M 0 0 ${segments.join(" ")} Z`;
}

const STAMP_OUTLINE = perforatedOutline(STAMP_WIDTH, STAMP_HEIGHT);

/** A city still to collect: the stamp's perforated silhouette, small, for the album's sheet of blanks. */
export function StampBlank() {
  return (
    <svg
      viewBox={`0 0 ${STAMP_WIDTH} ${STAMP_HEIGHT}`}
      aria-hidden
      className="h-full w-full"
    >
      <path d={STAMP_OUTLINE} className="fill-zinc-700/60" />
    </svg>
  );
}
