#!/usr/bin/env python3
"""
Script to index existing workflows in ChromaDB.
Stores all workflows from MongoDB into ChromaDB for semantic search.

Usage:
    python scripts/index_workflows_chromadb.py
"""

import asyncio
import sys
from pathlib import Path

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.agents.tools.core.store import init_embeddings  # noqa: E402
from app.config.loggers import general_logger as logger  # noqa: E402
from app.db.chroma.chromadb import ChromaClient, init_chromadb_constructor  # noqa: E402
from app.db.mongodb.collections import workflows_collection  # noqa: E402


async def index_workflows():
    """Index all workflows from MongoDB into ChromaDB."""
    try:
        logger.info("Starting workflow indexing...")

        # Initialize required providers
        init_embeddings()
        init_chromadb_constructor()

        chroma = await ChromaClient.get_langchain_client(
            "workflows", create_if_not_exists=True
        )

        workflows = await workflows_collection.find({}).to_list(length=None)
        logger.info(f"Found {len(workflows)} workflows to index")

        indexed = 0
        failed = 0

        for workflow in workflows:
            try:
                workflow_id = str(workflow["_id"])
                user_id = workflow.get("user_id", "unknown")
                title = workflow.get("title", "")
                description = workflow.get("description", "")
                trigger_type = workflow.get("trigger_config", {}).get("type", "manual")

                content = f"{title} | {description} | {trigger_type}"

                chroma.add_texts(
                    texts=[content],
                    metadatas=[
                        {
                            "user_id": user_id,
                            "workflow_id": workflow_id,
                            "trigger_type": trigger_type,
                        }
                    ],
                    ids=[workflow_id],
                )

                indexed += 1
                logger.info(f"Indexed workflow {workflow_id}: {title}")

            except Exception as e:
                failed += 1
                logger.error(f"Failed to index workflow {workflow.get('_id')}: {e}")

        logger.info(f"Indexing complete. Indexed: {indexed}, Failed: {failed}")

    except Exception as e:
        logger.error(f"Error during indexing: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(index_workflows())
