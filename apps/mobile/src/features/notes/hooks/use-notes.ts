import { useCallback, useEffect, useRef, useState } from "react";
import type { Note, NoteCreate, NoteUpdate } from "../api/notes-api";
import { notesApi } from "../api/notes-api";

interface UseNotesState {
  notes: Note[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
}

interface UseNotesReturn extends UseNotesState {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  refetch: () => Promise<void>;
  createNote: (data: NoteCreate) => Promise<Note>;
  updateNote: (id: string, data: NoteUpdate) => Promise<void>;
  deleteNote: (id: string) => Promise<void>;
}

export function useNotes(): UseNotesReturn {
  const [state, setState] = useState<UseNotesState>({
    notes: [],
    isLoading: true,
    isRefreshing: false,
    error: null,
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [searchQuery]);

  const fetchData = useCallback(
    async (isRefresh = false) => {
      setState((prev) => ({
        ...prev,
        isLoading: !isRefresh,
        isRefreshing: isRefresh,
        error: null,
      }));

      try {
        const notes = await notesApi.getNotes(debouncedSearch || undefined);
        setState((prev) => ({
          ...prev,
          notes,
          isLoading: false,
          isRefreshing: false,
        }));
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          isRefreshing: false,
          error: err instanceof Error ? err.message : "Failed to load notes",
        }));
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [debouncedSearch],
  );

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const refetch = useCallback(async () => {
    await fetchData(true);
  }, [fetchData]);

  const createNote = useCallback(async (data: NoteCreate): Promise<Note> => {
    const newNote = await notesApi.createNote(data);
    setState((prev) => ({ ...prev, notes: [newNote, ...prev.notes] }));
    return newNote;
  }, []);

  const updateNote = useCallback(
    async (id: string, data: NoteUpdate): Promise<void> => {
      const updated = await notesApi.updateNote(id, data);
      setState((prev) => ({
        ...prev,
        notes: prev.notes.map((n) => (n.id === id ? updated : n)),
      }));
    },
    [],
  );

  const deleteNote = useCallback(async (id: string): Promise<void> => {
    await notesApi.deleteNote(id);
    setState((prev) => ({
      ...prev,
      notes: prev.notes.filter((n) => n.id !== id),
    }));
  }, []);

  return {
    ...state,
    searchQuery,
    setSearchQuery,
    refetch,
    createNote,
    updateNote,
    deleteNote,
  };
}
