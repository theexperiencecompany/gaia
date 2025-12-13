"use client";

import { Input } from "@heroui/input";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/spinner";
import { PinCard } from "@/features/pins/components/PinCard";
import { usePins } from "@/features/pins/hooks/usePins";
import { PinIcon } from "@/icons";
import type { PinCardProps } from "@/types/features/pinTypes";

export default function Pins() {
  const { pins: fetchedResults, loading, fetchPins } = usePins();
  const [filteredResults, setFilteredResults] = useState<PinCardProps[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");

  useEffect(() => {
    fetchPins();
  }, [fetchPins]);

  useEffect(() => {
    setFilteredResults(fetchedResults);
  }, [fetchedResults]);

  const filterPins = (query: string) => {
    const filtered = fetchedResults.filter((result) =>
      result.message.response.toLowerCase().includes(query.toLowerCase()),
    );
    setFilteredResults(filtered);
  };

  return (
    <div className="flex h-full flex-col justify-between">
      <div className="overflow-y-auto">
        {loading ? (
          <div className="flex h-[90vh] items-center justify-center">
            <Spinner />
          </div>
        ) : (
          <div className="flex flex-wrap justify-center gap-4 pb-8">
            <div className="flex flex-wrap justify-center gap-4 pb-8 sm:px-[10vw]">
              {/* // <div className="grid gap-3 px-1 sm:px-[10%] sm:grid-cols-[repeat(auto-fill,minmax(15vw,1fr))] grid-cols-[repeat(auto-fill,minmax(1fr,1fr))] pb-24 sm:pb-20"> */}
              {!!filteredResults && filteredResults.length > 0 ? (
                <div className="grid grid-cols-1 gap-4 pt-10 pb-24 sm:grid-cols-3 sm:pb-20">
                  {filteredResults.map((result) => (
                    <PinCard
                      key={result.message.message_id}
                      conversation_id={result.conversation_id}
                      message={result.message}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex h-[90vh] flex-col items-center justify-center text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-zinc-800">
                    <PinIcon className="h-8 w-8 text-zinc-500" />
                  </div>
                  <div>
                    <h3 className="text-lg font-medium text-white">
                      {searchQuery.trim().length > 0
                        ? "No pins match your search"
                        : "No pinned messages yet"}
                    </h3>
                    <p className="mt-1 text-sm text-zinc-400">
                      {searchQuery.trim().length > 0
                        ? "Try adjusting your search terms or clear the filter"
                        : "PinIcon important messages during conversations to find them easily later"}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="absolute bottom-4 left-0 z-10 flex w-full flex-col items-center justify-center px-3 sm:bottom-5">
        <div className="relative flex w-full max-w-(--breakpoint-sm) items-center gap-3">
          <Input
            autoFocus
            className="w-full"
            classNames={{ inputWrapper: "pr-1" }}
            placeholder="Enter a message to filter pins"
            radius="full"
            size="lg"
            value={searchQuery}
            isClearable
            variant="faded"
            onValueChange={(query) => {
              setSearchQuery(query);
              filterPins(query);
            }}
          />
        </div>
      </div>
      <div className="bg-custom-gradient2 absolute bottom-0 left-0 z-1 h-[100px] w-full" />
    </div>
  );
}
