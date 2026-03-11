import { apiService } from "@/lib/api";

export interface Note {
  id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface NoteCreate {
  title: string;
  content: string;
}

export interface NoteUpdate {
  title?: string;
  content?: string;
}

export const notesApi = {
  getNotes: async (search?: string): Promise<Note[]> => {
    const query = search ? `?search=${encodeURIComponent(search)}` : "";
    return apiService.get<Note[]>(`/notes${query}`);
  },

  getNote: async (id: string): Promise<Note> => {
    return apiService.get<Note>(`/notes/${id}`);
  },

  createNote: async (data: NoteCreate): Promise<Note> => {
    return apiService.post<Note>("/notes", data);
  },

  updateNote: async (id: string, data: NoteUpdate): Promise<Note> => {
    return apiService.patch<Note>(`/notes/${id}`, data);
  },

  deleteNote: async (id: string): Promise<void> => {
    return apiService.delete(`/notes/${id}`);
  },
};
