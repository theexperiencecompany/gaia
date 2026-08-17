import asyncio
from collections.abc import Sequence
import re
import time
from typing import Annotated, Any, Union

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.agents.templates.fetch_template import FETCH_TEMPLATE
from app.constants.log_tags import LogTag
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.search_tool_docs import (
    WEB_SEARCH_TOOL,
)
from app.templates.docstrings.webpage_tool_docs import FETCH_WEBPAGES
from app.utils.search import perform_search
from app.utils.webpage_fetch import fetch_webpage
from shared.py.wide_events import log

_NO_URLS_RETRIEVED_MSG = (
    "Search failed — no URLs were retrieved. Do NOT fabricate any URLs or results."
)


@tool
@with_rate_limiting("webpage_fetch")
@with_doc(FETCH_WEBPAGES)
async def fetch_webpages(
    config: RunnableConfig,
    urls: Annotated[list[str], "List of URLs to fetch content from"],
    # state: Annotated[dict, InjectedState],
) -> dict[str, Union[str, Sequence[str]]]:
    try:
        log.set(tool={"name": "fetch_webpages", "action": "fetch"})
        if not urls:
            return {"error": "No URLs were provided for fetching."}

        processed_urls: list[str] = []
        combined_content = ""
        writer = get_stream_writer()

        for url in urls:
            writer({"progress": f"Processing URL: '{url:20}'..."})

            if not re.match(r"^https?://", url):
                processed_urls.append(f"https://{url}")
            else:
                processed_urls.append(url)

        fetch_tasks = [fetch_webpage(url) for url in processed_urls]
        fetched_pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for i, page_content in enumerate(fetched_pages):
            if isinstance(page_content, Exception):
                writer({"progress": f"Error processing {processed_urls[i]}: {page_content!s}"})
                continue

            combined_content += FETCH_TEMPLATE.format(
                page_content=page_content,
                urls=[processed_urls[i]],
            )

            writer({"progress": f"Processing Page {i + 1}/{len(fetched_pages)}..."})

        writer({"progress": "Fetching Complete!"})
        data = {"webpage_data": combined_content, "fetched_urls": processed_urls}

        # Send webpage data to frontend via writer
        writer(data)

        return data

    except Exception as e:
        return {"error": f"An error occurred while fetching webpages: {e!s}"}


@tool
@with_rate_limiting("web_search")
@with_doc(WEB_SEARCH_TOOL)
async def web_search_tool(
    query_text: Annotated[
        str,
        "The search query to look up on the web. Be specific and concise for better results.",
    ],
    config: RunnableConfig,
) -> dict[str, Any]:
    log.set(tool={"name": "web_search_tool", "action": "search"})
    start_time = time.time()

    try:
        # Get the langchain stream writer for progress updates
        writer = get_stream_writer()

        writer({"progress": f"Performing web search for '{query_text}'..."})

        # Perform the search with 10 results
        search_result = await perform_search(query=query_text, count=10)

        web_results = [item.model_dump() for item in search_result.web]
        # news_results = search_results.get("news", [])
        image_results = search_result.images
        video_results: list[str] = []
        answer = search_result.answer

        elapsed_time = time.time() - start_time
        formatted_text = f"Web search completed in {elapsed_time:.2f} seconds. Found {len(web_results)} web results, {len(image_results)} images, and {len(video_results)} videos."

        log.info(
            f"{LogTag.TOOL} Web search completed",
            duration_seconds=round(elapsed_time, 2),
            web_result_count=len(web_results),
            image_count=len(image_results),
            video_count=len(video_results),
        )
        writer({"progress": formatted_text})

        # Send search data to frontend via writer
        writer(
            {
                "search_results": {
                    "web": web_results,
                    "news": [],
                    "images": image_results,
                    "videos": video_results,
                    "query": query_text,
                    "elapsed_time": elapsed_time,
                    "answer": answer,
                    "response_time": 0,
                    "request_id": "",
                    "result_count": {
                        "web": len(web_results),
                        # "news": len(news_results),
                        "images": len(image_results),
                        "videos": len(video_results),
                    },
                }
            }
        )

        # Return the raw search results for the LLM to use
        # Include explicit URL list so the LLM has a ground-truth set and cannot hallucinate
        real_urls = [item.url for item in search_result.web if item.url]
        return {
            **search_result.model_dump(),
            "real_urls_from_search": real_urls,
            "integrity_note": (
                f"Search query: '{query_text}'. "
                f"Found {len(web_results)} real results. "
                "Only reference URLs listed in `real_urls_from_search` or in the `web` results. "
                "NEVER invent or fabricate URLs. If no results were found, say so clearly."
            ),
            "instructions": (
                "Summarise the search results — do not repeat them verbatim. "
                "Do not show images in markdown. "
                "Only mention URLs that appear in the search results. "
                "These results will be shown on the frontend in an appropriate manner."
            ),
        }

    except (TimeoutError, ConnectionError) as e:
        log.error(
            f"{LogTag.TOOL} Network error in web search", error_type=type(e).__name__, exc_info=True
        )
        return {
            "formatted_text": "\n\nConnection timed out during web search. Please try again later.",
            "error": str(e),
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
    except ValueError as e:
        log.error(
            f"{LogTag.TOOL} Value error in web search", error_type=type(e).__name__, exc_info=True
        )
        return {
            "formatted_text": "\n\nInvalid search parameters. Please try a different query.",
            "error": str(e),
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Unexpected error in web search",
            error_type=type(e).__name__,
            exc_info=True,
        )
        return {
            "formatted_text": "\n\nError performing web search. Please try again later.",
            "error": str(e),
            "real_urls_from_search": [],
            "integrity_note": _NO_URLS_RETRIEVED_MSG,
        }
