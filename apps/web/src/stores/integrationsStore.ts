import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface IntegrationsState {
  searchQuery: string;
  selectedCategory: string;
}

interface IntegrationsActions {
  setSearchQuery: (query: string) => void;
  setSelectedCategory: (category: string) => void;
  clearSearch: () => void;
  clearFilters: () => void;
}

type IntegrationsStore = IntegrationsState & IntegrationsActions;

const initialState: IntegrationsState = {
  searchQuery: "",
  selectedCategory: "all",
};

export const useIntegrationsStore = create<IntegrationsStore>()(
  devtools(
    (set) => ({
      ...initialState,

      setSearchQuery: (query) =>
        set({ searchQuery: query }, false, "setSearchQuery"),

      setSelectedCategory: (category) =>
        set({ selectedCategory: category }, false, "setSelectedCategory"),

      clearSearch: () => set({ searchQuery: "" }, false, "clearSearch"),

      clearFilters: () =>
        set(
          { searchQuery: "", selectedCategory: "all" },
          false,
          "clearFilters",
        ),
    }),
    { name: "integrations-store" },
  ),
);

// Selectors
export const useIntegrationsSearchQuery = () =>
  useIntegrationsStore((state) => state.searchQuery);

export const useIntegrationsCategory = () =>
  useIntegrationsStore((state) => state.selectedCategory);
