import asyncio
import re
import time
from typing import Annotated, Any, Dict, List, Sequence, Union

from app.agents.templates.fetch_template import FETCH_TEMPLATE
from app.config.loggers import chat_logger as logger
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.search_tool_docs import (
    WEB_SEARCH_TOOL,
)
from app.templates.docstrings.webpage_tool_docs import FETCH_WEBPAGES
from app.utils.search_utils import fetch_with_firecrawl, perform_search
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


@tool
@with_rate_limiting("webpage_fetch")
@with_doc(FETCH_WEBPAGES)
async def fetch_webpages(
    config: RunnableConfig,
    urls: Annotated[List[str], "List of URLs to fetch content from"],
    # state: Annotated[dict, InjectedState],
) -> Dict[str, Union[str, Sequence[str]]]:
    try:
        if not urls:
            return {"error": "No URLs were provided for fetching."}

        processed_urls: List[str] = []
        combined_content = ""
        writer = get_stream_writer()

        for url in urls:
            writer({"progress": f"Processing URL: '{url:20}'..."})

            if not re.match(r"^https?://", url):
                processed_urls.append(f"https://{url}")
            else:
                processed_urls.append(url)

        fetch_tasks = [fetch_with_firecrawl(url) for url in processed_urls]
        fetched_pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        for i, page_content in enumerate(fetched_pages):
            if isinstance(page_content, Exception):
                writer(
                    {
                        "progress": f"Error processing {processed_urls[i]}: {str(page_content)}"
                    }
                )
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
        return {"error": f"An error occurred while fetching webpages: {str(e)}"}


@tool
@with_rate_limiting("web_search")
@with_doc(WEB_SEARCH_TOOL)
async def web_search_tool(
    query_text: Annotated[
        str,
        "The search query to look up on the web. Be specific and concise for better results.",
    ],
    config: RunnableConfig,
) -> Dict[str, Any]:
    start_time = time.time()

    try:
        # Get the langchain stream writer for progress updates
        writer = get_stream_writer()

        writer({"progress": f"Performing web search for '{query_text}'..."})

        # Perform the search with 10 results
        search_results = await perform_search(query=query_text, count=10)

        web_results = search_results.get("web", [])
        # news_results = search_results.get("news", [])
        image_results = search_results.get("images", [])
        video_results = search_results.get("videos", [])
        answer = search_results.get("answer", "")

        elapsed_time = time.time() - start_time
        formatted_text = f"Web search completed in {elapsed_time:.2f} seconds. Found {len(web_results)} web results, {len(image_results)} images, and {len(video_results)} videos."

        logger.info(formatted_text)
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
                    "response_time": search_results.get("response_time", 0),
                    "request_id": search_results.get("request_id", ""),
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
        return {
            **search_results,
            "instructions": "Don't repeat the search results, just summarise them, don't show the images in markdown either. These results will be shown on the frontend in an appropriate manner",
        }

    except (asyncio.TimeoutError, ConnectionError) as e:
        logger.error(f"Network error in web search: {e}", exc_info=True)
        return {
            "formatted_text": "\n\nConnection timed out during web search. Please try again later.",
            "error": str(e),
        }
    except ValueError as e:
        logger.error(f"Value error in web search: {e}", exc_info=True)
        return {
            "formatted_text": "\n\nInvalid search parameters. Please try a different query.",
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Unexpected error in web search: {e}", exc_info=True)
        return {
            "formatted_text": "\n\nError performing web search. Please try again later.",
            "error": str(e),
        }


# @tool
# @with_rate_limiting("deep_research")
# @with_doc(DEEP_RESEARCH_TOOL)
# async def deep_research_tool(
#     query_text: Annotated[
#         str,
#         "The search query for in-depth research. Be specific to get thorough and comprehensive results.",
#     ],
#     config: RunnableConfig,
# ) -> Dict[str, Any]:
#     start_time = time.time()

#     try:
#         writer = get_stream_writer()
#         writer({"progress": f"Performing deep research for '{query_text}'..."})

#         deep_research_results = await perform_deep_research(
#             query=query_text, max_results=5
#         )

#         enhanced_results = deep_research_results.get("enhanced_results", [])
#         formatted_results = ""

#         if enhanced_results:
#             formatted_results = "## Deep Research Results\n\n"

#             for i, result in enumerate(enhanced_results, 1):
#                 title = result.get("title", "No Title")
#                 url = result.get("url", "#")
#                 snippet = result.get("snippet", "No snippet available")
#                 full_content = result.get("full_content", "")
#                 fetch_error = result.get("fetch_error", None)
#                 formatted_results += f"### {i}. {title}\n"
#                 formatted_results += f"**URL**: {url}\n\n"

#                 if fetch_error:
#                     formatted_results += (
#                         f"**Note**: Could not fetch full content: {fetch_error}\n\n"
#                     )
#                     formatted_results += f"**Summary**: {snippet}\n\n"
#                 else:
#                     formatted_results += f"**Summary**: {snippet}\n\n"
#                     formatted_results += "**Content**:\n"
#                     formatted_results += full_content + "\n\n"

#                 formatted_results += "---\n\n"
#         else:
#             formatted_results = "No detailed information found from deep research."

#         elapsed_time = time.time() - start_time
#         logger.info(f"Deep research completed in {elapsed_time:.2f} seconds")

#         # Send deep research data to frontend via writer
#         writer({"deep_research_results": deep_research_results})

#         # Return the raw deep research results for the LLM to use
#         return deep_research_results

#     except (asyncio.TimeoutError, ConnectionError) as e:
#         logger.error(f"Network error in deep research: {e}", exc_info=True)
#         return {
#             "formatted_text": "\n\nConnection timed out during deep research, falling back to standard results.",
#             "error": str(e),
#         }
#     except ValueError as e:
#         logger.error(f"Value error in deep research: {e}", exc_info=True)
#         return {
#             "formatted_text": "\n\nInvalid search parameters, falling back to standard results.",
#             "error": str(e),
#         }
#     except Exception as e:
#         logger.error(f"Unexpected error in deep research: {e}", exc_info=True)
#         return {
#             "formatted_text": "\n\nError performing deep research, falling back to standard results.",
#             "error": str(e),
#         }
