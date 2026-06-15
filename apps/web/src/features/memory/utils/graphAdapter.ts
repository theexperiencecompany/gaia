import type {
  GraphApiDocument,
  GraphApiMemory,
  MemoryRelation,
} from "@supermemory/memory-graph";
import type {
  MemoryEntry,
  MemoryGraphResponse,
} from "@/features/memory/api/types";

const UNFILED_FOLDER_LABEL = "Unfiled";
const FOLDER_DOC_PREFIX = "folder:";

type RelationsByMemoryId = Map<string, Record<string, MemoryRelation>>;

/**
 * Maps GAIA's entity graph onto @supermemory/memory-graph's document model:
 * - each entity becomes a document hex whose memories are the facts linked
 *   to it (a memory linked to several entities lives under the first and
 *   connects to the rest through `memoryRelations` edges);
 * - memories with no entities cluster under a synthetic document per
 *   top-level category folder;
 * - supersession lineage (parent_id + relation_type) renders as
 *   updates/extends/derives edges between memory versions;
 * - entity-to-entity edges connect through their provenance memory, since
 *   the component cannot draw document-to-document edges directly.
 */
export function adaptGraphResponse(
  response: MemoryGraphResponse,
): GraphApiDocument[] {
  const now = new Date().toISOString();
  const entityIds = new Set(response.nodes.map((node) => node.id));
  const relationsByMemoryId = collectRelations(response, entityIds);

  const folderDocs = new Map<string, GraphApiDocument>();
  const memoriesByDocId = assignMemoriesToDocs(
    response.memories,
    entityIds,
    relationsByMemoryId,
    folderDocs,
    now,
  );

  const summariesByEntityId = buildEntitySummaries(response);
  const entityDocs: GraphApiDocument[] = response.nodes.map((node) => {
    const memories = memoriesByDocId.get(node.id) ?? [];
    return {
      id: node.id,
      title: node.name,
      summary: summariesByEntityId.get(node.id) ?? null,
      documentType: node.entity_type,
      createdAt: memories[0]?.createdAt ?? now,
      updatedAt: memories[0]?.updatedAt ?? now,
      memories,
    };
  });

  const relationTargetIds = new Set(
    [...relationsByMemoryId.values()].flatMap((relations) =>
      Object.keys(relations),
    ),
  );
  return [...entityDocs, ...folderDocs.values()].filter(
    (doc) => doc.memories.length > 0 || relationTargetIds.has(doc.id),
  );
}

function collectRelations(
  response: MemoryGraphResponse,
  entityIds: Set<string>,
): RelationsByMemoryId {
  const memoryIds = new Set(
    response.memories.map((memory) => memory.id).filter(Boolean),
  );
  const relationsByMemoryId: RelationsByMemoryId = new Map();
  const addRelation = (
    memoryId: string,
    targetId: string,
    relation: MemoryRelation,
  ) => {
    const relations = relationsByMemoryId.get(memoryId) ?? {};
    relations[targetId] = relation;
    relationsByMemoryId.set(memoryId, relations);
  };

  for (const memory of response.memories) {
    if (!memory.id) continue;
    if (memory.parent_id && memoryIds.has(memory.parent_id)) {
      addRelation(
        memory.id,
        memory.parent_id,
        memory.relation_type ?? "updates",
      );
    }
    for (const entity of memory.entities.slice(1)) {
      if (entityIds.has(entity.id)) {
        addRelation(memory.id, entity.id, "derives");
      }
    }
  }

  for (const edge of response.edges) {
    if (!edge.memory_id || !memoryIds.has(edge.memory_id)) continue;
    for (const entityId of [edge.source_entity_id, edge.target_entity_id]) {
      if (entityIds.has(entityId)) {
        addRelation(edge.memory_id, entityId, "derives");
      }
    }
  }

  return relationsByMemoryId;
}

function assignMemoriesToDocs(
  memories: MemoryEntry[],
  entityIds: Set<string>,
  relationsByMemoryId: RelationsByMemoryId,
  folderDocs: Map<string, GraphApiDocument>,
  now: string,
): Map<string, GraphApiMemory[]> {
  const memoriesByDocId = new Map<string, GraphApiMemory[]>();

  for (const memory of memories) {
    if (!memory.id) continue;
    const primaryEntity = memory.entities.find((entity) =>
      entityIds.has(entity.id),
    );
    const docId = primaryEntity
      ? primaryEntity.id
      : getOrCreateFolderDoc(folderDocs, memory, now).id;
    const docMemories = memoriesByDocId.get(docId) ?? [];
    docMemories.push(toGraphMemory(memory, now, relationsByMemoryId));
    memoriesByDocId.set(docId, docMemories);
  }

  return memoriesByDocId;
}

function getOrCreateFolderDoc(
  folderDocs: Map<string, GraphApiDocument>,
  memory: MemoryEntry,
  now: string,
): GraphApiDocument {
  const folder = memory.category_path.split("/")[0] || "";
  const docId = `${FOLDER_DOC_PREFIX}${folder}`;
  const existing = folderDocs.get(docId);
  if (existing) return existing;

  const doc: GraphApiDocument = {
    id: docId,
    title: folder || UNFILED_FOLDER_LABEL,
    summary: null,
    documentType: "folder",
    createdAt: memory.created_at ?? now,
    updatedAt: memory.updated_at ?? now,
    memories: [],
  };
  folderDocs.set(docId, doc);
  return doc;
}

function buildEntitySummaries(
  response: MemoryGraphResponse,
): Map<string, string> {
  const entityNamesById = new Map(
    response.nodes.map((node) => [node.id, node.name]),
  );
  const sentencesByEntityId = new Map<string, string[]>();

  for (const edge of response.edges) {
    const sourceName = entityNamesById.get(edge.source_entity_id);
    const targetName = entityNamesById.get(edge.target_entity_id);
    if (!sourceName || !targetName) continue;
    const sentence = `${sourceName} ${edge.relationship} ${targetName}`;
    for (const entityId of [edge.source_entity_id, edge.target_entity_id]) {
      const sentences = sentencesByEntityId.get(entityId) ?? [];
      sentences.push(sentence);
      sentencesByEntityId.set(entityId, sentences);
    }
  }

  return new Map(
    [...sentencesByEntityId].map(([entityId, sentences]) => [
      entityId,
      sentences.join(". "),
    ]),
  );
}

function toGraphMemory(
  memory: MemoryEntry,
  fallbackTimestamp: string,
  relationsByMemoryId: RelationsByMemoryId,
): GraphApiMemory {
  const id = memory.id ?? "";
  const relations = relationsByMemoryId.get(id);
  return {
    id,
    memory: memory.content,
    content: memory.content,
    isStatic: false,
    spaceId: memory.category_path,
    isLatest: memory.is_latest,
    isForgotten: memory.is_forgotten,
    forgetAfter: memory.forget_after,
    forgetReason: null,
    version: memory.version,
    parentMemoryId: memory.parent_id,
    rootMemoryId: memory.root_id,
    createdAt: memory.created_at ?? fallbackTimestamp,
    updatedAt: memory.updated_at ?? memory.created_at ?? fallbackTimestamp,
    relation: memory.relation_type,
    memoryRelations: relations ?? null,
  };
}
