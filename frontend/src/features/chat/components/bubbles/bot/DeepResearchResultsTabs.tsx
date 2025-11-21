import { Accordion, AccordionItem } from "@heroui/accordion";
import { Tab, Tabs } from "@heroui/tabs";
import { useState } from "react";

import { ExternalLinkIcon, LinkIcon, SearchIcon } from "@/icons";
import { InternetIcon } from "@/icons";
import {
  DeepResearchResults,
  EnhancedWebResult,
} from "@/types/features/convoTypes";

import SearchResultsTabs from "./SearchResultsTabs";

interface DeepResearchResultsTabsProps {
  deep_research_results: DeepResearchResults;
}

export default function DeepResearchResultsTabs({
  deep_research_results,
}: DeepResearchResultsTabsProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const { original_search, enhanced_results, metadata } = deep_research_results;

  return (
    <div className="w-full">
      <Accordion
        className="w-full max-w-(--breakpoint-sm) px-0"
        defaultExpandedKeys={["1"]}
      >
        <AccordionItem
          key="1"
          aria-label="Deep Research Results"
          indicator={<></>}
          title={
            <div className="h-full w-fit rounded-lg bg-white/10 p-1 px-3 text-sm font-medium transition-all hover:bg-white/20">
              {isExpanded
                ? "Hide Deep research Results"
                : "Show Deep research Results"}
            </div>
          }
          onPress={() => setIsExpanded((prev) => !prev)}
          className="w-screen max-w-(--breakpoint-sm) px-0"
          isCompact
        >
          <Tabs
            aria-label="Deep Research Results"
            color="primary"
            variant="light"
            classNames={{ base: "p-0" }}
          >
            {enhanced_results && enhanced_results.length > 0 && (
              <Tab
                key="enhanced"
                title={
                  <div className="flex items-center space-x-2">
                    {/* <DocumentTextIcon className="h-4 w-4" /> */}
                    <span>Enhanced Results</span>
                  </div>
                }
              >
                <EnhancedWebResults results={enhanced_results} />
              </Tab>
            )}

            {original_search && (
              <Tab
                key="original"
                title={
                  <div className="flex items-center space-x-2">
                    <SearchIcon className="h-4 w-4" />
                    <span>Original Search</span>
                  </div>
                }
              >
                {original_search && (
                  <SearchResultsTabs search_results={original_search} />
                )}
              </Tab>
            )}

            {metadata && (
              <Tab
                key="metadata"
                title={
                  <div className="flex items-center space-x-2">
                    <InternetIcon color={undefined} />
                    <span>Search Info</span>
                  </div>
                }
              >
                <SearchMetadata metadata={metadata} />
              </Tab>
            )}
          </Tabs>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

interface EnhancedWebResultsProps {
  results: EnhancedWebResult[];
}

function EnhancedWebResults({ results }: EnhancedWebResultsProps) {
  return (
    <div className="space-y-4">
      {results.map((result, index) => (
        <div
          key={index}
          className="rounded-2xl bg-zinc-800 p-4 shadow-md transition-all hover:shadow-lg"
        >
          <h2 className="truncate text-sm font-medium text-primary">
            <a
              href={result.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-white"
            >
              {result.title}
            </a>
          </h2>

          <div className="mb-2 flex flex-wrap items-center gap-x-4 text-sm text-foreground-500">
            <span className="flex items-center gap-1">
              <LinkIcon width={13} height={13} />
              <a
                href={result.url}
                className="max-w-xs truncate hover:text-primary hover:underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                {(() => {
                  try {
                    return new URL(result.url).hostname;
                  } catch {
                    return result.url;
                  }
                })()}
              </a>
            </span>
          </div>

          {result.url && (
            <div className="mb-3 overflow-hidden rounded-lg">
              <a
                href={result.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group relative block"
              >
                <div className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition group-hover:opacity-100">
                  <ExternalLinkIcon className="h-8 w-8 text-white" />
                </div>
              </a>
            </div>
          )}

          {/* {result.full_content && (
            <div className="mt-2">
              <details className="group">
                <summary className="cursor-pointer list-none text-sm font-medium text-primary">
                  <span className="flex items-center">
                    View full content
                    <svg
                      className="ml-1 h-4 w-4 transition-transform group-open:rotate-180"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                  </span>
                </summary>
                <div className="mt-2 max-h-60 overflow-auto rounded-md bg-zinc-900 p-3 text-sm leading-relaxed text-foreground-400">
                  <p className="whitespace-pre-line">{result.full_content}</p>
                </div>
              </details>
            </div>
          )} */}
        </div>
      ))}
    </div>
  );
}

interface SearchMetadataProps {
  metadata: {
    total_content_size?: number;
    elapsed_time?: number;
    query?: string;
  };
}

function SearchMetadata({ metadata }: SearchMetadataProps) {
  return (
    <div className="rounded-lg bg-zinc-800 p-4">
      <h3 className="text-md mb-2 font-medium text-primary">
        Search Statistics
      </h3>
      <div className="space-y-2 text-sm">
        {metadata.query && (
          <div className="flex items-center justify-between">
            <span className="text-foreground-500">Search Query:</span>
            <span className="font-medium">{metadata.query}</span>
          </div>
        )}
        {metadata.elapsed_time && (
          <div className="flex items-center justify-between">
            <span className="text-foreground-500">Processing Time:</span>
            <span className="font-medium">
              {metadata.elapsed_time.toFixed(2)} seconds
            </span>
          </div>
        )}
        {metadata.total_content_size && (
          <div className="flex items-center justify-between">
            <span className="text-foreground-500">Content Size:</span>
            <span className="font-medium">
              {(metadata.total_content_size / 1024).toFixed(2)} KB
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
