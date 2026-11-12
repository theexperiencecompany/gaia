import { create } from "zustand";

interface ChatState {
  activeChatId: string | null;
  setActiveChatId: (id: string | null) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  activeChatId: null,
  setActiveChatId: (id) => set({ activeChatId: id }),
}));
