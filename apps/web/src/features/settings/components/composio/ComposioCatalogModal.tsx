"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Modal, ModalBody, ModalContent, ModalHeader } from "@heroui/modal";
import { Select, SelectItem } from "@heroui/select";
import { Skeleton } from "@heroui/skeleton";
import { Search01Icon } from "@icons";
import { useDeferredValue, useState } from "react";
import { ComposioKeyMissing } from "@/features/settings/components/composio/ComposioKeyMissing";
import { ComposioToolkitDetail } from "@/features/settings/components/composio/ComposioToolkitDetail";
import { ComposioToolkitListItem } from "@/features/settings/components/composio/ComposioToolkitListItem";
import { useComposioCatalog } from "@/features/settings/hooks/useComposioToolkits";
import { apiErrorMessage } from "@/lib/api/errorMessage";

const LIST_SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

interface ComposioCatalogModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Toolkit to show first, e.g. the integration whose setup row opened the modal. */
  initialSlug?: string | null;
}

/** Search Composio's full toolkit catalog and enable any toolkit on this instance. */
export function ComposioCatalogModal({
  isOpen,
  onClose,
  initialSlug = null,
}: ComposioCatalogModalProps) {
  const [search, setSearch] = useState(initialSlug ?? "");
  const [category, setCategory] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(initialSlug);
  const query = useDeferredValue(search);
  const catalog = useComposioCatalog(query, category);

  const entries = catalog.data?.pages.flatMap((page) => page.items) ?? [];
  const total = catalog.data?.pages[0]?.total ?? 0;
  const categories = catalog.data?.pages[0]?.categories ?? [];
  const needsKey = catalog.data?.pages[0]?.composio_configured === false;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="4xl"
      placement="center"
      scrollBehavior="inside"
      backdrop="blur"
      className="rounded-2xl shadow-none"
    >
      <ModalContent>
        <ModalHeader className="flex flex-col gap-1">
          <h2 className="text-xl font-semibold">Composio catalog</h2>
          <p className="text-sm font-normal text-zinc-400">
            Enable any app Composio supports. GAIA creates its auth config in
            your Composio project, then everyone on this instance can connect it
            from the integrations page.
          </p>
        </ModalHeader>
        <ModalBody className="pb-6">
          {needsKey ? (
            <ComposioKeyMissing onNavigate={onClose} />
          ) : (
            <>
              <div className="flex gap-2">
                <Input
                  aria-label="Search toolkits"
                  placeholder="Search 1,600+ apps"
                  value={search}
                  onValueChange={setSearch}
                  startContent={
                    <Search01Icon className="size-4 text-zinc-500" />
                  }
                  autoFocus
                />
                <Select
                  aria-label="Category"
                  placeholder="All categories"
                  className="w-56"
                  selectedKeys={category ? [category] : []}
                  onSelectionChange={(keys) => {
                    const [first] = Array.from(keys);
                    setCategory(first === undefined ? null : String(first));
                  }}
                >
                  {categories.map((name) => (
                    <SelectItem key={name}>{name}</SelectItem>
                  ))}
                </Select>
              </div>

              <div className="grid min-h-[420px] grid-cols-1 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="flex max-h-[480px] flex-col gap-1 overflow-y-auto rounded-2xl bg-zinc-900 p-2">
                  {catalog.isLoading &&
                    LIST_SKELETON_KEYS.map((key) => (
                      <Skeleton key={key} className="h-12 w-full rounded-xl" />
                    ))}
                  {catalog.error && (
                    <p className="p-3 text-sm text-zinc-400">
                      {apiErrorMessage(catalog.error) ??
                        "Couldn't load the catalog. Try again in a moment."}
                    </p>
                  )}
                  {!catalog.isLoading &&
                    !catalog.error &&
                    entries.length === 0 && (
                      <p className="p-3 text-sm text-zinc-400">
                        No app matches that search.
                      </p>
                    )}
                  {entries.map((toolkit) => (
                    <ComposioToolkitListItem
                      key={toolkit.slug}
                      toolkit={toolkit}
                      isSelected={toolkit.slug === selected}
                      onSelect={setSelected}
                    />
                  ))}
                  {catalog.hasNextPage && (
                    <Button
                      size="sm"
                      variant="flat"
                      isLoading={catalog.isFetchingNextPage}
                      onPress={() => void catalog.fetchNextPage()}
                    >
                      Show more ({total - entries.length} left)
                    </Button>
                  )}
                </div>

                <div className="rounded-2xl bg-zinc-800 p-4">
                  {selected ? (
                    <ComposioToolkitDetail key={selected} slug={selected} />
                  ) : (
                    <p className="text-sm text-zinc-400">
                      Pick an app to see what enabling it takes.
                    </p>
                  )}
                </div>
              </div>
            </>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
