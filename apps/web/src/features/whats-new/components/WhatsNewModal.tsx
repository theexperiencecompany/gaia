"use client";

import { Button, Modal, Spinner } from "@heroui/react";
import { ArrowLeft02Icon, ArrowRight02Icon, ArrowUpRight01Icon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { LinkButton } from "@/components/shared/LinkButton";
import { track } from "@/lib/analytics";
import { useWhatsNewModal, useWhatsNewStore } from "@/stores/whatsNewStore";
import { useReleases } from "../hooks/useReleases";
import { WhatsNewRecentReleases } from "./WhatsNewRecentReleases";
import { WhatsNewSlide } from "./WhatsNewSlide";

export function WhatsNewModal() {
  const { isModalOpen, modalInitialIndex, closeModal } = useWhatsNewModal();
  const markAllSeen = useWhatsNewStore((s) => s.markAllSeen);
  const { releases, latest, isLoading } = useReleases();
  const hasMarkedSeenRef = useRef(false);

  const [selectedIndex, setSelectedIndex] = useState(modalInitialIndex);
  const lastTrackedRef = useRef(-1);
  const scrollRef = useRef<HTMLDivElement>(null);

  const canScrollPrev = selectedIndex > 0;
  const canScrollNext = selectedIndex < releases.length - 1;

  const scrollPrev = useCallback(() => {
    if (!canScrollPrev) return;
    setSelectedIndex((i) => i - 1);
  }, [canScrollPrev]);

  const scrollNext = useCallback(() => {
    if (!canScrollNext) return;
    setSelectedIndex((i) => i + 1);
  }, [canScrollNext]);

  // Jump to a release from the recent-releases footer and bring its hero back
  // into view (the user clicked from the bottom of the scroll area).
  const selectRelease = useCallback((index: number) => {
    setSelectedIndex(index);
    scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  // Track slide views
  useEffect(() => {
    if (!isModalOpen) return;
    if (selectedIndex === lastTrackedRef.current) return;
    lastTrackedRef.current = selectedIndex;
    const release = releases[selectedIndex];
    if (release) {
      track("whats_new:slide_viewed", {
        releaseId: release.id,
        index: selectedIndex,
      });
    }
  }, [selectedIndex, releases, isModalOpen]);

  // Mark all seen once when modal opens
  useEffect(() => {
    if (!isModalOpen || hasMarkedSeenRef.current) return;
    if (!latest) return;
    hasMarkedSeenRef.current = true;
    markAllSeen(latest.id, latest.date);
    track("whats_new:modal_opened", { source: "modal" });
  }, [isModalOpen, latest, markAllSeen]);

  useEffect(() => {
    if (isModalOpen) {
      setSelectedIndex(modalInitialIndex);
    } else {
      hasMarkedSeenRef.current = false;
      lastTrackedRef.current = -1;
    }
  }, [isModalOpen, modalInitialIndex]);

  const showControls = !isLoading && releases.length > 0;
  const release = releases[selectedIndex];

  return (
    <Modal isOpen={isModalOpen} onOpenChange={closeModal}>
      <Modal.Backdrop>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header>What&apos;s new in GAIA</Modal.Header>

            <Modal.Body>
              {isLoading ? (
                <div className="flex h-40 items-center justify-center">
                  <Spinner size="sm" color="accent" />
                </div>
              ) : releases.length === 0 ? (
                <p className="py-8 text-center text-sm text-zinc-500">
                  No releases found.
                </p>
              ) : (
                <div
                  ref={scrollRef}
                  className="overflow-y-auto"
                  style={{ maxHeight: "70vh" }}
                >
                  {release && (
                    <WhatsNewSlide
                      release={release}
                      isFirst={selectedIndex === 0}
                    />
                  )}
                  <WhatsNewRecentReleases
                    releases={releases}
                    currentIndex={selectedIndex}
                    onSelect={selectRelease}
                  />
                </div>
              )}
            </Modal.Body>

            {showControls && (
              <Modal.Footer className="flex items-center justify-between">
                {release && (
                  <LinkButton
                    href={release.docsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    variant="tertiary"
                    size="sm"
                    onClick={() =>
                      track("whats_new:docs_clicked", { releaseId: release.id })
                    }
                  >
                    View all release notes
                    <ArrowUpRight01Icon className="h-3.5 w-3.5" />
                  </LinkButton>
                )}
                <div className="flex items-center gap-1">
                  <Button
                    isIconOnly
                    variant="tertiary"
                    size="sm"
                    isDisabled={!canScrollPrev}
                    onPress={scrollPrev}
                    aria-label="Previous release"
                    className="h-7 w-7 min-w-7 bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30"
                  >
                    <ArrowLeft02Icon className="h-4 w-4" />
                  </Button>
                  <Button
                    isIconOnly
                    variant="tertiary"
                    size="sm"
                    isDisabled={!canScrollNext}
                    onPress={scrollNext}
                    aria-label="Next release"
                    className="h-7 w-7 min-w-7 bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30"
                  >
                    <ArrowRight02Icon className="h-4 w-4" />
                  </Button>
                </div>
              </Modal.Footer>
            )}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
