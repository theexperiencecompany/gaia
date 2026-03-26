export interface Note {
  id: string;
  title?: string;
  content: string;
  plaintext: string;
  description?: string;
  auto_created: boolean;
  user_id?: string;
  createdAt?: string;
  updatedAt?: string;
  tags?: string[];
}

export interface NoteCreate {
  title?: string;
  content: string;
  plaintext: string;
  tags?: string[];
}

export interface NoteUpdate {
  title?: string;
  content?: string;
  plaintext?: string;
  tags?: string[];
}

export interface NoteListResponse {
  notes: Note[];
  total: number;
  hasMore: boolean;
}
