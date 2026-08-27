"""ChromaDB-backed implementation of LangGraph's BaseStore interface.

This module provides a persistent, scalable alternative to InMemoryStore
using ChromaDB for vector storage and retrieval.
"""

import asyncio
from collections.abc import Coroutine, Iterable
from datetime import UTC, datetime
import pickle  # nosec B403 - Used for internal trusted data serialization only
from typing import Any, cast

from chromadb.api import AsyncClientAPI
from chromadb.api.models.AsyncCollection import AsyncCollection
from langchain_core.embeddings import Embeddings
from langgraph.store.base import (
    BaseStore,
    GetOp,
    IndexConfig,
    Item,
    ListNamespacesOp,
    MatchCondition,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
    ensure_embeddings,
    get_text_at_path,
    tokenize_path,
)

from app.constants.chroma import MAX_CONCURRENT_CHROMA_WRITES
from app.constants.log_tags import LogTag
from app.db.chroma.noop_embedding import NoOpEmbeddingFunction
from app.utils.concurrency import loop_bound_semaphore
from shared.py.wide_events import VectorContext, log

# A filter value (or the item value it's compared against) is an arbitrary
# JSON-like scalar/container pulled out of a MongoDB-style query filter dict.
FilterValue = str | int | float | bool | None | dict[str, Any] | list[Any]


class ChromaStore(BaseStore):
    """ChromaDB-backed store with vector search capabilities.

    This store provides persistent storage for documents with semantic search
    capabilities using ChromaDB as the backend.
    """

    __slots__ = (
        "_collection_cache",
        "_tokenized_fields",
        "client",
        "collection_name",
        "embeddings",
        "index_config",
    )

    def __init__(
        self,
        client: AsyncClientAPI,
        collection_name: str = "langgraph_store",
        *,
        index: IndexConfig | None = None,
    ) -> None:
        """Initialize ChromaStore.

        Args:
            client: ChromaDB async client
            collection_name: Name of the ChromaDB collection
            index: Index configuration with embeddings and fields
        """
        self.client = client
        self.collection_name = collection_name
        self._collection_cache: AsyncCollection | None = None

        self.index_config = index
        if self.index_config:
            self.index_config = self.index_config.copy()
            self.embeddings: Embeddings | None = ensure_embeddings(
                self.index_config.get("embed"),
            )
            # Store tokenized fields separately to avoid TypedDict issues
            self._tokenized_fields = [
                (p, tokenize_path(p)) if p != "$" else (p, p)
                for p in (self.index_config.get("fields") or ["$"])
            ]
        else:
            self.index_config = None
            self.embeddings = None
            self._tokenized_fields = []

    async def _get_collection(self) -> AsyncCollection:
        """Get or create the ChromaDB collection.

        Uses ``NoOpEmbeddingFunction`` as the collection-level embedding function so
        ChromaDB never attempts to load its default ONNX model.  ChromaStore
        manages embeddings itself via ``self.embeddings`` and always passes
        them explicitly to ``collection.upsert()``.
        """
        if self._collection_cache is None:
            log.set(
                vector=VectorContext(
                    operation="get_or_create_collection",
                    collection=self.collection_name,
                )
            )
            try:
                self._collection_cache = await self.client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"hnsw:space": "cosine"},
                    embedding_function=NoOpEmbeddingFunction(),
                )
            except ValueError:
                # ChromaDB 1.x rejects a new embedding function when one is
                # already persisted in the collection config.  Since
                # ChromaStore manages embeddings itself (passes them
                # explicitly to upsert), we can safely resolve the collection
                # without overriding the embedding function.
                self._collection_cache = await self.client.get_or_create_collection(
                    name=self.collection_name,
                )

        return self._collection_cache

    def _namespace_to_id(self, namespace: tuple[str, ...], key: str) -> str:
        """Convert namespace tuple and key to ChromaDB ID."""
        ns_str = "::".join(namespace) if namespace else "default"
        return f"{ns_str}::{key}"

    def _id_to_namespace_key(self, id_str: str) -> tuple[tuple[str, ...], str]:
        """Convert ChromaDB ID back to namespace tuple and key."""
        parts = id_str.split("::")
        if len(parts) < 2:
            return ((), parts[0])
        key = parts[-1]
        ns = tuple(parts[:-1]) if parts[:-1] != ["default"] else ()
        return ns, key

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute a batch of operations (sync wrapper)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "ChromaStore.batch() cannot be called from async context. Use abatch() instead."
            )
        return asyncio.run(self.abatch(ops))

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute a batch of operations (async version)."""
        collection = await self._get_collection()
        results, put_ops, search_ops, search_error = await self._prepare_ops(ops, collection)

        if search_error is None and search_ops:
            try:
                await self._batch_search(search_ops, results, collection)
            except Exception as e:
                search_error = e

        # A sibling read failing must never drop durable writes: apply the queued
        # puts before surfacing the search failure, so a batch that mixes SearchOp
        # and PutOp still persists its writes when the search path raises.
        if put_ops:
            await self._apply_put_ops(put_ops, collection)

        if search_error is not None:
            raise search_error

        return results

    async def _prepare_ops(
        self, ops: Iterable[Op], collection: AsyncCollection
    ) -> tuple[
        list[Result],
        dict[tuple[tuple[str, ...], str], PutOp],
        dict[int, tuple[SearchOp, list[str]]],
        Exception | None,
    ]:
        """Prepare operations for execution.

        Search filtering runs here; a filter failure is captured and returned
        (not raised) so ``abatch`` can still apply sibling writes before it
        surfaces the error.
        """
        ops_list = list(ops)
        results: list[Result] = [None] * len(ops_list)
        put_ops: dict[tuple[tuple[str, ...], str], PutOp] = {}
        search_ops: dict[int, tuple[SearchOp, list[str]]] = {}
        search_error: Exception | None = None

        # Collect async operations to parallelize
        get_tasks = []
        search_tasks = []
        list_ns_tasks = []

        for i, op in enumerate(ops_list):
            if isinstance(op, GetOp):
                get_tasks.append((i, self._get_item(op.namespace, op.key, collection)))
            elif isinstance(op, SearchOp):
                search_tasks.append((i, self._filter_items(op, collection)))
            elif isinstance(op, ListNamespacesOp):
                list_ns_tasks.append((i, self._handle_list_namespaces(op, collection)))
            elif isinstance(op, PutOp):
                put_ops[(op.namespace, op.key)] = op
            else:
                raise ValueError(f"Unknown operation type: {type(op)}")

        # Execute all async operations in parallel
        if get_tasks:
            get_results = await asyncio.gather(*[task for _, task in get_tasks])
            for (idx, _), result in zip(get_tasks, get_results):
                results[idx] = result

        if search_tasks:
            try:
                search_results = await asyncio.gather(*[task for _, task in search_tasks])
            except Exception as e:
                # Capture the first filter failure; writes in the same batch still
                # run in abatch() before this is re-raised.
                search_error = e
            else:
                for (idx, _), candidate_ids in zip(search_tasks, search_results):
                    op = ops_list[idx]
                    if isinstance(op, SearchOp):
                        search_ops[idx] = (op, candidate_ids)

        if list_ns_tasks:
            list_ns_results = await asyncio.gather(*[task for _, task in list_ns_tasks])
            for (idx, _), namespaces in zip(list_ns_tasks, list_ns_results):
                results[idx] = namespaces

        return results, put_ops, search_ops, search_error

    async def _get_item(
        self, namespace: tuple[str, ...], key: str, collection: AsyncCollection
    ) -> Item | None:
        """Get a single item from ChromaDB."""
        doc_id = self._namespace_to_id(namespace, key)
        try:
            result = await collection.get(ids=[doc_id], include=["metadatas", "documents"])

            if not result["ids"]:
                return None

            metadata = result["metadatas"][0] if result["metadatas"] else {}
            document = result["documents"][0] if result["documents"] else None

            # Deserialize value from document (stored as pickle base64).
            # Trust boundary: this document was written by this store (_put below); ChromaDB
            # data is service-private — never untrusted input — so pickle.loads is safe here.
            value = pickle.loads(document.encode("latin1")) if document else {}  # nosec B301 - Internal trusted data only

            created_at_str = metadata.get("created_at")
            updated_at_str = metadata.get("updated_at")

            return Item(
                value=value,
                key=key,
                namespace=namespace,
                created_at=datetime.fromisoformat(str(created_at_str))
                if created_at_str and isinstance(created_at_str, str)
                else datetime.now(UTC),
                updated_at=datetime.fromisoformat(str(updated_at_str))
                if updated_at_str and isinstance(updated_at_str, str)
                else datetime.now(UTC),
            )
        except Exception as e:
            log.error(
                f"{LogTag.CHROMA} Error getting item",
                doc_id=doc_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _filter_items(self, op: SearchOp, collection: AsyncCollection) -> list[str]:
        """Filter items by namespace prefix and filter conditions."""
        try:
            result = await collection.get(include=["metadatas", "documents"])

            if not result["ids"]:
                return []

            # Pre-filter by namespace (fast operation, no deserialization)
            filtered_by_ns = []
            for idx, doc_id in enumerate(result["ids"]):
                ns, _ = self._id_to_namespace_key(doc_id)
                if self._matches_namespace_prefix(ns, op.namespace_prefix):
                    filtered_by_ns.append((idx, doc_id))

            if not filtered_by_ns:
                return []

            # If no filter, return early (avoid unnecessary pickle deserialization)
            if not op.filter:
                return [doc_id for _, doc_id in filtered_by_ns]

            # Apply filter conditions (slower, but only on pre-filtered set)
            filtered_ids = []
            for idx, doc_id in filtered_by_ns:
                document = result["documents"][idx] if result["documents"] else None
                if not document:
                    continue
                try:
                    # Trust boundary: documents come from our own _put writes (service-private
                    # ChromaDB collection), never untrusted input.
                    value = pickle.loads(document.encode("latin1"))  # nosec B301 - Internal trusted data only
                except Exception as e:
                    log.debug(
                        f"{LogTag.CHROMA} Failed to deserialize document at index",
                        idx=idx,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    continue
                if not isinstance(value, dict):
                    continue
                if self._check_filter(value, op.filter):
                    filtered_ids.append(doc_id)

            return filtered_ids
        except Exception as e:
            # Re-raise so callers can tell an unreachable ChromaDB apart from an
            # empty namespace (same contract as the write path). Per-document
            # data issues are already handled item-by-item above.
            log.error(f"{LogTag.CHROMA} Error filtering items", error_type=type(e).__name__)
            raise

    def _matches_namespace_prefix(
        self, namespace: tuple[str, ...], prefix: tuple[str, ...]
    ) -> bool:
        """Check if namespace matches prefix."""
        if len(namespace) < len(prefix):
            return False
        return namespace[: len(prefix)] == prefix

    def _check_filter(self, value: dict, filter_dict: dict) -> bool:
        """Check if value matches filter conditions."""
        for key, filter_value in filter_dict.items():
            if key.startswith("$"):
                if not self._apply_operator(value, key, filter_value):
                    return False
            else:
                item_value = value.get(key)
                if isinstance(filter_value, dict):
                    if not isinstance(item_value, dict):
                        return False
                    if not self._check_filter(item_value, filter_value):
                        return False
                elif item_value != filter_value:
                    return False
        return True

    def _apply_operator(self, value: FilterValue, operator: str, op_value: FilterValue) -> bool:
        """Apply comparison operator."""
        if operator == "$eq":
            return bool(value == op_value)
        if operator == "$ne":
            return bool(value != op_value)
        if operator in ("$gt", "$gte", "$lt", "$lte"):
            try:
                # dict is excluded above (comparison undefined); list/None reach
                # float() and raise TypeError, caught below — same behavior as
                # before FilterValue existed. cast() only narrows for the type
                # checker, it doesn't change what's passed at runtime.
                val_num = (
                    float(cast("str | float | int | bool", value))
                    if not isinstance(value, dict)
                    else 0
                )
                op_val_num = float(cast("str | float | int | bool", op_value))
                if operator == "$gt":
                    return val_num > op_val_num
                if operator == "$gte":
                    return val_num >= op_val_num
                if operator == "$lt":
                    return val_num < op_val_num
                if operator == "$lte":
                    return val_num <= op_val_num
            except (ValueError, TypeError):
                return False
        else:
            raise ValueError(f"Unsupported operator: {operator}")
        return False

    async def _batch_search(
        self,
        ops: dict[int, tuple[SearchOp, list[str]]],
        results: list[Result],
        collection: AsyncCollection,
    ) -> None:
        """Perform batch similarity search."""
        for i, (op, candidate_ids) in ops.items():
            if not candidate_ids:
                results[i] = []
                continue

            if op.query and self.embeddings:
                # Vector search with ChromaDB's native where filter for namespace
                query_embedding = await self.embeddings.aembed_query(op.query)

                try:
                    # Build where filter for namespace prefix
                    where_filter: dict[str, Any] | None = None
                    if op.namespace_prefix:
                        namespace_str = "::".join(op.namespace_prefix)
                        where_filter = {"namespace": {"$eq": namespace_str}}

                    # Apply additional filters if provided
                    if op.filter:
                        # Combine namespace filter with op.filter if both exist
                        if where_filter:
                            where_filter = {"$and": [where_filter, op.filter]}
                        else:
                            where_filter = op.filter

                    # Use ChromaDB's native query with where filter
                    search_result = await collection.query(
                        query_embeddings=[query_embedding],  # type: ignore[arg-type]  # chromadb stubs demand ndarrays; a single float vector is valid at runtime
                        n_results=op.limit + op.offset,
                        include=["metadatas", "distances", "documents"],
                        where=where_filter,
                    )

                    items = []
                    if (
                        search_result["ids"]
                        and search_result["ids"][0]
                        and search_result["metadatas"]
                        and search_result["metadatas"][0]
                        and search_result["distances"]
                        and search_result["distances"][0]
                    ):
                        for idx, (doc_id, metadata, distance) in enumerate(
                            zip(
                                search_result["ids"][0],
                                search_result["metadatas"][0],
                                search_result["distances"][0],
                            )
                        ):
                            ns, key = self._id_to_namespace_key(doc_id)

                            # Get document from search results
                            documents = search_result.get("documents")
                            document = documents[0][idx] if documents and documents[0] else None
                            value = (
                                # Trust boundary: documents come from our own _put writes
                                # (service-private ChromaDB collection), never untrusted input.
                                pickle.loads(document.encode("latin1"))  # nosec B301 - Internal trusted data only
                                if document
                                else {}
                            )

                            created_at_str = metadata.get("created_at")
                            updated_at_str = metadata.get("updated_at")

                            # Convert distance to similarity score
                            score = 1.0 - distance if distance is not None else None

                            items.append(
                                SearchItem(
                                    namespace=ns,
                                    key=key,
                                    value=value,
                                    created_at=datetime.fromisoformat(str(created_at_str))
                                    if created_at_str and isinstance(created_at_str, str)
                                    else datetime.now(UTC),
                                    updated_at=datetime.fromisoformat(str(updated_at_str))
                                    if updated_at_str and isinstance(updated_at_str, str)
                                    else datetime.now(UTC),
                                    score=float(score) if score is not None else None,
                                )
                            )

                    # Apply pagination
                    results[i] = items[op.offset : op.offset + op.limit]
                except Exception as e:
                    # Re-raise so an unreachable ChromaDB doesn't masquerade as
                    # zero search hits (same contract as the write path).
                    log.error(
                        f"{LogTag.CHROMA} Error in vector search", error_type=type(e).__name__
                    )
                    raise
            else:
                # No query, just return filtered items with pagination
                # Parallelize item retrieval
                paginated_ids = candidate_ids[op.offset : op.offset + op.limit]
                item_tasks = [
                    self._get_item(*self._id_to_namespace_key(doc_id), collection)
                    for doc_id in paginated_ids
                ]
                retrieved_items = await asyncio.gather(*item_tasks)

                items = [
                    SearchItem(
                        namespace=item.namespace,
                        key=item.key,
                        value=item.value,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                    )
                    for item in retrieved_items
                    if item is not None
                ]
                results[i] = items

    async def _apply_put_ops(
        self,
        put_ops: dict[tuple[tuple[str, ...], str], PutOp],
        collection: AsyncCollection,
    ) -> None:
        """Apply put operations to ChromaDB in parallel."""
        tasks: list[Coroutine[Any, Any, None]] = []
        doc_ids: list[str] = []

        for (namespace, key), op in put_ops.items():
            doc_id = self._namespace_to_id(namespace, key)
            doc_ids.append(doc_id)

            if op.value is None:
                tasks.append(self._delete_item(doc_id, collection))
            else:
                tasks.append(self._upsert_item(doc_id, op, collection))

        if not tasks:
            return

        # Process-wide, not per-call: concurrent _apply_put_ops calls (e.g. the
        # startup catalog warmup fanning out over every provider toolkit) share
        # this one semaphore, so the fd cap holds across callers, not just
        # within a single batch.
        sem = loop_bound_semaphore("chroma_put_batch", MAX_CONCURRENT_CHROMA_WRITES)

        async def _guarded(coro: Coroutine[Any, Any, None]) -> None:
            async with sem:
                await coro

        # return_exceptions=True keeps one bad doc from killing the batch, but
        # silently swallows every failure. Surface them so we don't end up with
        # an indexing pass that "succeeded" yet wrote zero rows (the PostHog
        # case — 336 tools "indexed", 0 in ChromaDB, no errors anywhere).
        results: list[BaseException | None] = await asyncio.gather(
            *[_guarded(t) for t in tasks], return_exceptions=True
        )
        failures: list[tuple[str, BaseException]] = [
            (d, r) for d, r in zip(doc_ids, results) if isinstance(r, BaseException)
        ]
        succeeded = len(results) - len(failures)
        log.info(
            f"{LogTag.CHROMA} _apply_put_ops completed",
            results_count=len(results),
            succeeded=succeeded,
            failures_count=len(failures),
        )
        if failures:
            # Show up to 3 distinct exception classes to make patterns obvious.
            sample = failures[: min(3, len(failures))]
            for d, exc in sample:
                log.error(
                    f"{LogTag.CHROMA} _apply_put_ops failure",
                    doc_id=d,
                    error_type=type(exc).__name__,
                )

    async def _delete_item(self, doc_id: str, collection: AsyncCollection) -> None:
        """Delete a single item.

        Re-raises so the caller's asyncio.gather(return_exceptions=True) can
        count the failure. Previously this swallowed the exception and made
        _apply_put_ops's failure tally meaningless (succeeded count == total
        regardless of actual ChromaDB rejections).
        """
        try:
            await collection.delete(ids=[doc_id])
        except Exception as e:
            log.error(
                f"{LogTag.CHROMA} Error deleting item", doc_id=doc_id, error_type=type(e).__name__
            )
            raise

    async def _upsert_item(self, doc_id: str, op: PutOp, collection: AsyncCollection) -> None:
        """Upsert a single item."""
        now = datetime.now(UTC)
        # Store namespace in metadata for efficient filtering
        namespace_str = "::".join(op.namespace) if op.namespace else "default"
        metadata = {
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "namespace": namespace_str,
        }

        # Add tool_hash to metadata if provided in value
        if isinstance(op.value, dict) and "tool_hash" in op.value:
            metadata["tool_hash"] = op.value["tool_hash"]

        # Serialize value to document
        document = pickle.dumps(op.value).decode("latin1")

        # Extract embedding from indexed fields
        embedding = None
        if (
            isinstance(op.value, dict)
            and "embedding" in op.value
            and isinstance(op.value["embedding"], list)
        ):
            embedding = op.value["embedding"]
        elif self.embeddings and op.index is not False and isinstance(op.value, dict):
            paths = (
                [(ix, tokenize_path(ix)) for ix in op.index]
                if op.index
                else self._tokenized_fields or [("$", "$")]
            )
            texts = []
            for _, field in paths:
                field_texts = get_text_at_path(op.value, field)
                if field_texts:
                    texts.extend(field_texts)
            if texts:
                try:
                    embedding = await self.embeddings.aembed_query(" ".join(texts))
                except Exception as embed_err:
                    log.error(
                        f"{LogTag.CHROMA} _upsert_item embedding failed",
                        doc_id=doc_id,
                        namespace=namespace_str,
                        text_len=sum(len(t) for t in texts),
                        error_type=type(embed_err).__name__,
                    )
                    raise

        try:
            await collection.upsert(
                ids=[doc_id],
                embeddings=[embedding] if embedding else None,  # type: ignore[arg-type]  # same stub looseness: optional single vector vs Sequence[ndarray]
                metadatas=[metadata],
                documents=[document],
            )
        except Exception as e:
            # Re-raise so _apply_put_ops's failure count is accurate.
            log.error(
                f"{LogTag.CHROMA} Error upserting item",
                doc_id=doc_id,
                namespace=namespace_str,
                error_type=type(e).__name__,
            )
            raise

    async def _handle_list_namespaces(
        self, op: ListNamespacesOp, collection: AsyncCollection
    ) -> list[tuple[str, ...]]:
        """List all namespaces matching conditions."""
        try:
            result = await collection.get(include=["metadatas"])

            if not result["ids"]:
                return []

            namespaces = set()
            for doc_id in result["ids"]:
                ns, _ = self._id_to_namespace_key(doc_id)

                # Apply match conditions
                if op.match_conditions:
                    if not all(self._does_match(cond, ns) for cond in op.match_conditions):
                        continue

                # Apply max depth
                if op.max_depth is not None:
                    ns = ns[: op.max_depth]

                namespaces.add(ns)

            sorted_namespaces = sorted(namespaces)
            return sorted_namespaces[op.offset : op.offset + op.limit]
        except Exception as e:
            log.error(
                f"{LogTag.CHROMA} Error listing namespaces",
                error=str(e),
                error_type=type(e).__name__,
            )
            return []

    def _does_match(self, match_condition: MatchCondition, key: tuple[str, ...]) -> bool:
        """Check if namespace matches condition."""
        match_type = match_condition.match_type
        path = match_condition.path

        if len(key) < len(path):
            return False

        if match_type == "prefix":
            for k_elem, p_elem in zip(key, path):
                if p_elem == "*":
                    continue
                if k_elem != p_elem:
                    return False
            return True
        if match_type == "suffix":
            for k_elem, p_elem in zip(reversed(key), reversed(path)):
                if p_elem == "*":
                    continue
                if k_elem != p_elem:
                    return False
            return True
        raise ValueError(f"Unsupported match type: {match_type}")
