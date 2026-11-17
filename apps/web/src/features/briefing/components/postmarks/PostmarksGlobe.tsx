"use client";

import type { Postmark } from "@shared/api/generated";
import type { ProjectionSpecification } from "maplibre-gl";
import { useMemo } from "react";

import {
  MapArc,
  type MapArcDatum,
  MapMarker,
  MapView,
  MarkerContent,
  MarkerTooltip,
} from "@/components/ui/map";
import { useGlobeSpin } from "../../hooks/useGlobeSpin";
import { useNightGlobeBasemap } from "../../hooks/useNightGlobeBasemap";
import type { BriefTriggerState } from "../../hooks/useOpenBrief";
import { postmarkBrief } from "../../utils/briefCard";
import { BriefingFold } from "../BriefingFold";
import { BriefTrigger } from "../BriefTrigger";
import { PostmarkCard } from "./PostmarkCard";

const GLOBE_PROJECTION: ProjectionSpecification = { type: "globe" };
const GLOBE_ZOOM = 1.2;
// Where the globe faces before any stamp has arrived.
const DEFAULT_CENTER: [number, number] = [20, 20];
// The mail's route: a faint brand-cyan thread (--color-primary), so the city lights stay the subject.
const ROUTE_PAINT = {
  "line-color": "#00bbff",
  "line-width": 1.25,
  "line-opacity": 0.45,
  "line-dasharray": [2, 2],
};

interface PostmarksGlobeProps {
  postmarks: Postmark[];
}

/** The world at night, lit where the user's Air Mail came from and threaded in arrival order. */
export function PostmarksGlobe({ postmarks }: PostmarksGlobeProps) {
  const latest = postmarks.at(-1);
  const route = useMemo<MapArcDatum[]>(
    () =>
      postmarks.slice(1).map((postmark, index) => ({
        id: postmark.city_slug,
        from: [postmarks[index].lng, postmarks[index].lat],
        to: [postmark.lng, postmark.lat],
      })),
    [postmarks],
  );

  return (
    <MapView
      projection={GLOBE_PROJECTION}
      center={latest ? [latest.lng, latest.lat] : DEFAULT_CENTER}
      zoom={GLOBE_ZOOM}
      theme="dark"
      minZoom={1}
      maxZoom={4}
      attributionControl={{ compact: true }}
      className="h-full w-full"
    >
      <GlobeBehaviour />
      <MapArc
        data={route}
        curvature={0.25}
        interactive={false}
        paint={ROUTE_PAINT}
      />
      {postmarks.map((postmark) => (
        <CityLight
          key={postmark.city_slug}
          postmark={postmark}
          isLatest={postmark === latest}
        />
      ))}
    </MapView>
  );
}

function GlobeBehaviour() {
  useNightGlobeBasemap();
  useGlobeSpin();
  return null;
}

interface CityLightProps {
  postmark: Postmark;
  isLatest: boolean;
}

/** A city's light; pressing it unfolds the brief its stamp came on, as the album's stamps do. */
function CityLight({ postmark, isLatest }: CityLightProps) {
  return (
    <BriefingFold
      briefingId={postmark.briefing_id}
      brief={postmarkBrief(postmark)}
    >
      {(trigger) => (
        <CityMarker postmark={postmark} isLatest={isLatest} trigger={trigger} />
      )}
    </BriefingFold>
  );
}

function CityMarker({
  postmark,
  isLatest,
  trigger,
}: CityLightProps & { trigger: BriefTriggerState }) {
  return (
    <MapMarker longitude={postmark.lng} latitude={postmark.lat}>
      <MarkerContent>
        <BriefTrigger
          trigger={trigger}
          onPress={() => trigger.open()}
          aria-label={`${postmark.city}, ${postmark.country}`}
          className="group relative flex size-6 items-center justify-center rounded-full"
        >
          {isLatest && (
            <span className="absolute size-4 rounded-full bg-accent/40 motion-safe:animate-ping" />
          )}
          <span className="size-2.5 rounded-full bg-accent shadow-[0_0_10px_3px_rgb(0_187_255/0.55)] transition-transform duration-200 ease-out group-hover:scale-150 group-focus-visible:scale-150" />
        </BriefTrigger>
      </MarkerContent>
      <MarkerTooltip offset={18} className="bg-transparent p-0 shadow-none">
        <PostmarkCard postmark={postmark} />
      </MarkerTooltip>
    </MapMarker>
  );
}
