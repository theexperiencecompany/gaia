import asyncio
import json
import time
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.config.loggers import chat_logger as logger
from app.templates.docstrings.search_tool_docs import (
    WEB_SEARCH_TOOL,
    DEEP_RESEARCH_TOOL,
)
from app.decorators import with_doc, with_rate_limiting
from app.utils.internet_utils import perform_deep_research
from app.utils.search_utils import format_results_for_llm, perform_search


@tool
@with_rate_limiting("web_search")
@with_doc(WEB_SEARCH_TOOL)
async def web_search_tool(
    query_text: Annotated[
        str,
        "The search query to look up on the web. Be specific and concise for better results.",
    ],
    config: RunnableConfig,
) -> str:
    start_time = time.time()

    try:
        # Get the langchain stream writer for progress updates
        writer = get_stream_writer()

        writer({"progress": f"Performing web search for '{query_text}'..."})

        # Perform the search with 5 results
        search_results = await perform_search(query=query_text, count=5)

        web_results = search_results.get("web", [])
        news_results = search_results.get("news", [])
        image_results = search_results.get("images", [])
        video_results = search_results.get("videos", [])
        formatted_results = ""

        if web_results:
            formatted_results += (
                format_results_for_llm(web_results, result_type="Web Results") + "\n\n"
            )

        if news_results:
            formatted_results += format_results_for_llm(
                news_results, result_type="News Results"
            )

        if not formatted_results.strip():
            formatted_results = "No relevant search results found for your query."

        elapsed_time = time.time() - start_time
        formatted_text = f"Web search completed in {elapsed_time:.2f} seconds. Found {len(web_results)} web results and {len(news_results)} news results."

        logger.info(formatted_text)
        writer({"progress": formatted_text})

        # Send search data to frontend via writer
        writer(
            {
                "search_results": {
                    "web": web_results,
                    "news": news_results,
                    "images": image_results,
                    "videos": video_results,
                    "query": query_text,
                    "elapsed_time": elapsed_time,
                    "result_count": {
                        "web": len(web_results),
                        "news": len(news_results),
                    },
                }
            }
        )

        return "Search results sent to frontend"

    except (asyncio.TimeoutError, ConnectionError) as e:
        logger.error(f"Network error in web search: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nConnection timed out during web search. Please try again later.",
            "error": str(e),
        }
        return json.dumps(error_response)
    except ValueError as e:
        logger.error(f"Value error in web search: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nInvalid search parameters. Please try a different query.",
            "error": str(e),
        }
        return json.dumps(error_response)
    except Exception as e:
        logger.error(f"Unexpected error in web search: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nError performing web search. Please try again later.",
            "error": str(e),
        }
        return json.dumps(error_response)


@tool
@with_rate_limiting("deep_research")
@with_doc(DEEP_RESEARCH_TOOL)
async def deep_research_tool(
    query_text: Annotated[
        str,
        "The search query for in-depth research. Be specific to get thorough and comprehensive results.",
    ],
    config: RunnableConfig,
) -> str:
    start_time = time.time()

    try:
        writer = get_stream_writer()
        writer({"progress": f"Performing deep research for '{query_text}'..."})

        deep_research_results = await perform_deep_research(
            query=query_text, max_results=5, take_screenshots=True
        )

        enhanced_results = deep_research_results.get("enhanced_results", [])
        formatted_results = ""

        if enhanced_results:
            formatted_results = "## Deep Research Results\n\n"

            for i, result in enumerate(enhanced_results, 1):
                title = result.get("title", "No Title")
                url = result.get("url", "#")
                snippet = result.get("snippet", "No snippet available")
                full_content = result.get("full_content", "")
                fetch_error = result.get("fetch_error", None)
                screenshot_url = result.get("screenshot_url", None)
                formatted_results += f"### {i}. {title}\n"
                formatted_results += f"**URL**: {url}\n\n"

                if screenshot_url:
                    formatted_results += f"**Screenshot**: ![Screenshot of {title}]({screenshot_url})\n\n"

                if fetch_error:
                    formatted_results += (
                        f"**Note**: Could not fetch full content: {fetch_error}\n\n"
                    )
                    formatted_results += f"**Summary**: {snippet}\n\n"
                else:
                    formatted_results += f"**Summary**: {snippet}\n\n"
                    formatted_results += "**Content**:\n"
                    formatted_results += full_content + "\n\n"

                formatted_results += "---\n\n"
        else:
            formatted_results = "No detailed information found from deep research."

        elapsed_time = time.time() - start_time
        logger.info(f"Deep research completed in {elapsed_time:.2f} seconds")

        # Send deep research data to frontend via writer
        writer({"deep_research_results": deep_research_results})

        return "Deep research results sent to frontend"

    except (asyncio.TimeoutError, ConnectionError) as e:
        logger.error(f"Network error in deep research: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nConnection timed out during deep research, falling back to standard results.",
            "error": str(e),
        }
        return json.dumps(error_response)
    except ValueError as e:
        logger.error(f"Value error in deep research: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nInvalid search parameters, falling back to standard results.",
            "error": str(e),
        }
        return json.dumps(error_response)
    except Exception as e:
        logger.error(f"Unexpected error in deep research: {e}", exc_info=True)
        error_response = {
            "formatted_text": "\n\nError performing deep research, falling back to standard results.",
            "error": str(e),
        }
        return json.dumps(error_response)
