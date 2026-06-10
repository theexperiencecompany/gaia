import { ScrollView, View } from "react-native";
import { AppIcon, Search01Icon } from "@/components/icons";
import { useResponsive } from "@/lib/responsive";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import {
  AppFilterChipGroup,
  type AppFilterChipOption,
} from "@/shared/components/ui/app-filter-chip-group";
import { AppSearchInput } from "@/shared/components/ui/app-search-input";
import { WORKFLOW_COLORS } from "../../constants/colors";
import type { CommunityWorkflow } from "../../types/workflow-types";
import { CommunityWorkflowCard } from "../community-workflow-card";
import { SectionHeader } from "../section-header";

interface ExploreWorkflowsListProps {
  workflows: CommunityWorkflow[];
  filtered: CommunityWorkflow[];
  search: string;
  onSearchChange: (value: string) => void;
  categories: string[];
  selectedCategory: string | null;
  onCategoryChange: (next: string | null) => void;
}

const ALL_KEY = "__all__";

export function ExploreWorkflowsList({
  workflows,
  filtered,
  search,
  onSearchChange,
  categories,
  selectedCategory,
  onCategoryChange,
}: ExploreWorkflowsListProps) {
  const { spacing } = useResponsive();

  if (workflows.length === 0 && !search && !selectedCategory) {
    return null;
  }

  const chipOptions: AppFilterChipOption[] = [
    { key: ALL_KEY, label: "All" },
    ...categories.map((cat) => ({ key: cat, label: cat })),
  ];

  const handleSelect = (key: string | undefined) => {
    if (!key || key === ALL_KEY) {
      onCategoryChange(null);
      return;
    }
    onCategoryChange(key);
  };

  return (
    <View style={{ gap: spacing.md }}>
      <SectionHeader
        title="Explore & Discover"
        description="See what's possible with real examples that actually work!"
        count={filtered.length > 0 ? filtered.length : undefined}
      />

      <View style={{ flexDirection: "row" }}>
        <AppSearchInput
          className="flex-1"
          value={search}
          onChangeText={onSearchChange}
          placeholder="Search workflows"
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="search"
        />
      </View>

      {categories.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingVertical: 2 }}
        >
          <AppFilterChipGroup
            options={chipOptions}
            selectedKey={selectedCategory ?? ALL_KEY}
            onSelect={handleSelect}
            allowsEmptySelection={false}
          />
        </ScrollView>
      ) : null}

      {filtered.length === 0 ? (
        <AppEmptyStateCard
          title="No workflows match your search"
          icon={
            <AppIcon
              icon={Search01Icon}
              size={28}
              color={WORKFLOW_COLORS.textZinc700}
            />
          }
          className="rounded-2xl bg-zinc-800/30"
        />
      ) : (
        <View style={{ gap: spacing.sm }}>
          {filtered.map((w) => (
            <CommunityWorkflowCard key={w.id} workflow={w} />
          ))}
        </View>
      )}
    </View>
  );
}
