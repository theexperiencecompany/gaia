import type React from "react";

import type { SearchMode } from "@/types/shared";

import ComposerLeft from "./ComposerLeft";
import SearchbarRightSendBtn from "./ComposerRight";

interface SearchbarToolbarProps {
  selectedMode: Set<SearchMode>;
  openFileUploadModal: () => void;
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  handleSelectionChange: (mode: SearchMode) => void;
  searchbarText: string;
  selectedTool?: string | null;
  onToggleSlashCommandDropdown?: () => void;
  isSlashCommandDropdownOpen?: boolean;
}

const ComposerToolbar: React.FC<SearchbarToolbarProps> = ({
  selectedMode,
  openFileUploadModal,
  handleFormSubmit,
  handleSelectionChange,
  searchbarText,
  selectedTool,
  onToggleSlashCommandDropdown,
  isSlashCommandDropdownOpen,
}) => {
  return (
    <div className="flex items-center justify-between px-2 pt-1">
      <div className="flex items-center justify-start gap-2">
        <ComposerLeft
          selectedMode={selectedMode}
          openFileUploadModal={openFileUploadModal}
          handleSelectionChange={handleSelectionChange}
          onOpenSlashCommandDropdown={onToggleSlashCommandDropdown}
          isSlashCommandDropdownOpen={isSlashCommandDropdownOpen}
        />
      </div>
      <div className="flex items-center gap-2">
        <SearchbarRightSendBtn
          handleFormSubmit={handleFormSubmit}
          searchbarText={searchbarText}
          selectedTool={selectedTool}
        />
      </div>
    </div>
  );
};

export default ComposerToolbar;
