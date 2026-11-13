import type { NewsResult, SearchResults, WebResult } from "../../../chat/types";
import { formatDate } from "../../../utils/dateUtils";
import type { Card, CardBlock, CardListItem } from "../types";
import { cappedList, httpsUrl, joinMeta, snippet, urlHost } from "./card-parts";

const SEARCH_TITLE = "Search results";
const NEWS_HEADING = "News";
/**
 * Past this many the list stops and says how many more there are: two lists of
 * four keep the card inside a Telegram widget's 600 px.
 */
const MAX_LISTED_RESULTS = 4;
/** Enough of a snippet to tell results apart. */
const SNIPPET_MAX = 160;

/** Only results the user can open are listed. */
function linked<T extends { url?: string }>(
  results: readonly T[] | undefined,
): Array<T & { url: string }> {
  return (results ?? []).flatMap((result) => {
    const url = httpsUrl(result.url);
    return url ? [{ ...result, url }] : [];
  });
}

function webItem(result: WebResult & { url: string }): CardListItem {
  const host = urlHost(result.url);
  return {
    title: result.title || host,
    url: result.url,
    meta: host,
    body: snippet(result.snippet ?? result.content, SNIPPET_MAX),
  };
}

function newsItem(result: NewsResult & { url: string }): CardListItem {
  return {
    title: result.title || urlHost(result.url),
    url: result.url,
    meta: joinMeta([
      result.source ?? urlHost(result.url),
      result.published_date ? formatDate(result.published_date) : null,
    ]),
    body: snippet(result.content, SNIPPET_MAX),
  };
}

/**
 * What a web search found: the pages and the news, each opening the source.
 * Image results are left out: a third-party image the platform cannot fetch
 * fails the whole message.
 */
export function buildSearchResultsCards(data: SearchResults): Card[] {
  const web = linked(data.web);
  const news = linked(data.news);
  const blocks: CardBlock[] = [];
  if (web.length > 0) blocks.push(cappedList(web, MAX_LISTED_RESULTS, webItem));
  if (news.length > 0) {
    blocks.push(
      { kind: "text", markdown: `**${NEWS_HEADING}**` },
      cappedList(news, MAX_LISTED_RESULTS, newsItem),
    );
  }
  if (blocks.length === 0) return [];
  return [
    {
      title: data.query ? `${SEARCH_TITLE} for "${data.query}"` : SEARCH_TITLE,
      accent: "brand",
      blocks,
      actions: [],
    },
  ];
}
