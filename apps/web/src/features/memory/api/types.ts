/**
 * TypeScript mirror of the backend memory contract
 * (apps/api/app/models/memory_models.py). Field names are snake_case
 * because they come straight from the API.
 */

export type MemoryKind = "fact" | "experience";

export type MemoryRelationType = "updates" | "extends" | "derives";

export type MemoryEntityType =
  | "person"
  | "place"
  | "organization"
  | "project"
  | "topic"
  | "other";

export type MemorySourceType =
  | "conversation"
  | "tool"
  | "email"
  | "manual"
  | "migration";

export type MemoryDocType =
  | "user_md"
  | "memory_md"
  | "agenda_md"
  | "people_md"
  | "insights_md";

export interface MemoryEntityRef {
  id: string;
  name: string;
  entity_type: MemoryEntityType;
}

export interface MemoryEntry {
  id: string | null;
  content: string;
  kind: MemoryKind;
  category_path: string;
  importance: number;
  occurred_start: string | null;
  occurred_end: string | null;
  mentioned_at: string | null;
  version: number;
  is_latest: boolean;
  parent_id: string | null;
  root_id: string | null;
  relation_type: MemoryRelationType | null;
  is_forgotten: boolean;
  forget_after: string | null;
  source_type: MemorySourceType;
  source_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  relevance_score: number | null;
  entities: MemoryEntityRef[];
}

export interface MemoryListResponse {
  memories: MemoryEntry[];
  page: number;
  page_size: number;
  total_count: number;
}

export interface MemorySearchResult {
  memories: MemoryEntry[];
  total_count: number;
}

export interface MemoryTreeNode {
  name: string;
  path: string;
  count: number;
  children: MemoryTreeNode[];
  memories: MemoryEntry[] | null;
}

export interface MemoryTreeResponse {
  tree: MemoryTreeNode[];
  total_count: number;
}

export interface MemoryGraphNode {
  id: string;
  name: string;
  entity_type: MemoryEntityType;
  memory_count: number;
}

export interface MemoryGraphEdge {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship: string;
  memory_id: string | null;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  memories: MemoryEntry[];
}

export interface MemoryEpisodeEntry {
  time: string;
  text: string;
  source: string;
}

export interface MemoryEpisode {
  date: string;
  entries: MemoryEpisodeEntry[];
  summary: string | null;
}

export interface MemoryEpisodesResponse {
  episodes: MemoryEpisode[];
}

export interface MemoryDocument {
  doc_type: MemoryDocType;
  content: string;
  version: number;
  updated_at: string;
}

export interface MemoryDocumentsResponse {
  documents: MemoryDocument[];
}

export interface MemoryDocumentPreview {
  doc_type: MemoryDocType;
  preview: string;
  updated_at: string;
}

export interface MemoryOverviewResponse {
  total_memories: number;
  total_entities: number;
  folder_count: number;
  episode_count: number;
  documents: MemoryDocumentPreview[];
}

export interface CreateMemoryRequest {
  content: string;
  category_path?: string;
}

export interface CreateMemoryResponse {
  success: boolean;
  memory_id: string | null;
  message: string;
}

export interface DeleteMemoryResponse {
  success: boolean;
  message: string;
}
