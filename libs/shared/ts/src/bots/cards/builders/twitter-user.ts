import type { TwitterUserData } from "../../../chat/types";
import { formatDate } from "../../../utils/dateUtils";
import { formatCompactNumber } from "../../../utils/formatters";
import type { Card, CardBlock, CardField, CardListItem } from "../types";
import { cappedList, countOf, httpsUrl, joinMeta } from "./card-parts";
import { xHandle, xNameWithHandle, xProfileUrl } from "./twitter-links";

const PROFILES_TITLE = "X profiles";
const OPEN_LABEL = "Open on X";
const BIO_CITE = "Bio";
/** Past this many the list stops and says how many more there are. */
const MAX_LISTED_PROFILES = 8;

function metricFields(user: TwitterUserData): CardField[] {
  const metrics = user.public_metrics;
  const counted: [string, number | undefined][] = [
    ["Followers", metrics?.followers_count],
    ["Following", metrics?.following_count],
    ["Posts", metrics?.tweet_count],
  ];
  return counted.flatMap(([label, value]) =>
    value == null
      ? []
      : [{ label, value: formatCompactNumber(value), inline: true }],
  );
}

function profileFields(user: TwitterUserData): CardField[] {
  const fields = metricFields(user);
  if (user.location) {
    fields.push({ label: "Location", value: user.location, inline: true });
  }
  if (user.created_at) {
    fields.push({
      label: "Joined",
      value: formatDate(user.created_at, "long"),
      inline: true,
    });
  }
  return fields;
}

/** One profile, as the web card shows it: who, their bio, their numbers. */
function profileCard(user: TwitterUserData): Card {
  const blocks: CardBlock[] = [];
  const fields = profileFields(user);
  if (fields.length > 0) blocks.push({ kind: "fields", fields });
  const bio = user.description?.trim();
  if (bio) {
    blocks.push({
      kind: "quote",
      markdown: bio,
      collapsible: true,
      cite: BIO_CITE,
    });
  }
  return {
    title: xNameWithHandle(user),
    thumbnailUrl: httpsUrl(user.profile_image_url),
    accent: "brand",
    blocks,
    actions: [
      { kind: "link", label: OPEN_LABEL, url: xProfileUrl(user.username) },
    ],
  };
}

function profileItem(user: TwitterUserData): CardListItem {
  return {
    title: user.name,
    url: xProfileUrl(user.username),
    meta: joinMeta([
      xHandle(user.username),
      countOf(user.public_metrics?.followers_count, "follower"),
    ]),
    body: user.description?.trim() || undefined,
  };
}

/** The X profile(s) a lookup returned: one full card, or a list of several. */
export function buildTwitterUserCards(users: TwitterUserData[]): Card[] {
  if (users.length === 0) return [];
  if (users.length === 1) return [profileCard(users[0])];
  return [
    {
      title: PROFILES_TITLE,
      accent: "brand",
      blocks: [cappedList(users, MAX_LISTED_PROFILES, profileItem)],
      actions: [],
    },
  ];
}
