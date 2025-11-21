import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import React, { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/shadcn/dialog";
import Spinner from "@/components/ui/shadcn/spinner";
import { mailApi } from "@/features/mail/api/mailApi";
import { AiSearch02Icon } from "@/icons";

import { EmailChip, EmailSuggestion } from "./EmailChip";

export interface AiSearchModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (selectedSuggestions: EmailSuggestion[]) => void;
}

export const AiSearchModal: React.FC<AiSearchModalProps> = ({
  open,
  onOpenChange,
  onSelect,
}) => {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<EmailSuggestion[]>([]);
  const [selected, setSelected] = useState<EmailSuggestion[]>([]);

  const handleSearch = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!query) return;

    setLoading(true);
    setResults([]);

    try {
      const response = await mailApi.searchEmails(query);

      if (response?.emails?.length) {
        setResults(
          response.emails.map((email: string, index: number) => ({
            id: `${index + 1}`,
            email,
            name: email.split("@")[0], // Extract name from email
          })),
        );
      } else {
        setResults([]); // No emails found
      }
    } catch (error) {
      console.error("Error fetching emails:", error);
      setResults([]); // Handle API failure gracefully
    } finally {
      setLoading(false);
    }
  };

  const toggleSelection = (suggestion: EmailSuggestion) => {
    setSelected((prevSelected) =>
      prevSelected.find((s) => s.id === suggestion.id)
        ? prevSelected.filter((s) => s.id !== suggestion.id)
        : [...prevSelected, suggestion],
    );
  };

  // Toggles selection of all chips
  const handleSelectAll = () => {
    if (selected.length === results.length) {
      setSelected([]);
    } else {
      setSelected(results);
    }
  };

  const handleConfirm = () => {
    onSelect(selected);
    onOpenChange(false);
    setQuery("");
    setResults([]);
    setSelected([]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="border-none bg-zinc-900 outline-hidden"
        aria-description="Dialog box to search the internet for email suggestions."
      >
        <DialogHeader>
          <DialogTitle>Search the Internet for Email?</DialogTitle>
          <DialogDescription>
            Enter a search term to find email suggestions.
          </DialogDescription>
        </DialogHeader>

        {/* Form for search input */}
        <form onSubmit={handleSearch} className="flex gap-2">
          <Input
            placeholder="Company/Person/Organization"
            value={query}
            variant="faded"
            isClearable
            startContent={
              <div className="text-sm font-medium text-nowrap text-foreground-500">
                Find email of
              </div>
            }
            onValueChange={setQuery}
          />
          <Button type="submit" disabled={loading || !query} color="primary">
            {loading ? (
              <Spinner />
            ) : (
              <div className="flex items-center gap-1">
                Search
                <AiSearch02Icon width={19} />
              </div>
            )}
          </Button>
        </form>

        {/* Display email results with Select All support */}
        {results.length > 0 ? (
          <div className="mt-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-foreground-500">
                {results.length} suggestion
                {results.length > 1 ? "s" : ""}
              </span>
              <Button
                onPress={handleSelectAll}
                // color="secondary"
                variant="flat"
                size="sm"
              >
                {selected.length === results.length
                  ? "Deselect All"
                  : "Select All"}
              </Button>
            </div>
            <div className="flex flex-wrap gap-1">
              {results.map((suggestion) => (
                <EmailChip
                  key={suggestion.id}
                  suggestion={suggestion}
                  selected={!!selected.find((s) => s.id === suggestion.id)}
                  onToggle={toggleSelection}
                />
              ))}
            </div>
          </div>
        ) : (
          !loading &&
          query && (
            <div className="mt-3 text-sm text-foreground-500">
              No email suggestions found.
            </div>
          )
        )}

        {/* Disclaimer */}
        <div className="mt-3 text-xs text-gray-400">
          Disclaimer: Email suggestions are sourced from publicly available
          internet data and may not be 100% accurate.
        </div>

        {/* Action Buttons */}
        <div className="mt-4 flex justify-end gap-2">
          <Button
            color="danger"
            variant="light"
            onPress={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={handleConfirm}
            disabled={selected.length === 0}
          >
            Confirm
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
};
