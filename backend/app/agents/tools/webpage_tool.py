import asyncio
import re
from typing import Annotated, Dict, List, Union, Sequence

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.templates.docstrings.webpage_tool_docs import FETCH_WEBPAGES
from app.decorators import with_doc, with_rate_limiting
from app.agents.templates.fetch_template import FETCH_TEMPLATE
from app.utils.search_utils import fetch_with_firecrawl


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
