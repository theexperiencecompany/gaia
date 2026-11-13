import type {
  DeepResearchResults,
  DeepResearchSource,
  EnhancedWebResult,
} from "../../../chat/types";
import type { Card, CardBlock, CardListItem } from "../types";
import { cappedList, httpsUrl, snippet, urlHost } from "./card-parts";

const RESEARCH_TITLE = "Deep research";
const SOURCES_LABEL = "Sources";
/** Past this many the list stops and says how many more there are. */
const MAX_LISTED_FINDINGS = 5;
/** Enough of each finding to say what the source contributed. */
const FINDING_SNIPPET_MAX = 200;

/** One researched page, read by the web card as a title, its site and what it says. */
interface Finding {
  title?: string;
  url: string;
  text?: string;
}

function fromEnhanced(result: EnhancedWebResult): Finding[] {
  const url = httpsUrl(result.url);
  if (!url) return [];
  return [{ title: result.title, url, text: result.snippet ?? result.content }];
}

function fromSource(source: DeepResearchSource): Finding[] {
  const url = httpsUrl(source.url);
  return url ? [{ title: source.title, url, text: source.snippet }] : [];
}

/** The read-in pages when the research got that far, else the sources it streamed. */
function findings(data: DeepResearchResults): Finding[] {
  const enhanced = (data.enhanced_results ?? []).flatMap(fromEnhanced);
  return enhanced.length > 0
    ? enhanced
    : (data.sources ?? []).flatMap(fromSource);
}

function findingItem(finding: Finding): CardListItem {
  const host = urlHost(finding.url);
  return {
    title: finding.title || host,
    url: finding.url,
    meta: host,
    body: snippet(finding.text, FINDING_SNIPPET_MAX),
  };
}

/** The finished research: what it was about, how many sources, and the key ones. */
export function buildDeepResearchCards(data: DeepResearchResults): Card[] {
  const found = findings(data);
  if (found.length === 0) return [];
  const sourceCount = data.totalSources ?? found.length;
  const query = data.metadata?.query ?? data.original_search?.query;
  const blocks: CardBlock[] = [
    {
      kind: "fields",
      fields: [{ label: SOURCES_LABEL, value: String(sourceCount) }],
    },
    cappedList(found, MAX_LISTED_FINDINGS, findingItem),
  ];
  return [
    {
      title: query ? `${RESEARCH_TITLE}: ${query}` : RESEARCH_TITLE,
      accent: "brand",
      blocks,
      actions: [],
    },
  ];
}

/** Only the finished research is posted; the streamed progress frames are not results. */
export function isDeepResearchPosted(data: DeepResearchResults): boolean {
  return data.status !== "running";
}
