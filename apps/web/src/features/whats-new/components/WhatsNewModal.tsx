"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Spinner } from "@heroui/spinner";
import { ArrowLeft02Icon, ArrowRight02Icon, ArrowUpRight01Icon } from "@icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useWhatsNewModal, useWhatsNewStore } from "@/stores/whatsNewStore";
import { useReleases } from "../hooks/useReleases";
import { WhatsNewSlide } from "./WhatsNewSlide";

export function WhatsNewModal() {
  const { isModalOpen, modalInitialIndex, closeModal } = useWhatsNewModal();
  const markAllSeen = useWhatsNewStore((s) => s.markAllSeen);
  const { releases, latest, isLoading } = useReleases();
  const hasMarkedSeenRef = useRef(false);

  const [selectedIndex, setSelectedIndex] = useState(modalInitialIndex);
  const lastTrackedRef = useRef(-1);

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

  // Track slide views
  useEffect(() => {
    if (!isModalOpen) return;
    if (selectedIndex === lastTrackedRef.current) return;
    lastTrackedRef.current = selectedIndex;
    const release = releases[selectedIndex];
    if (release) {
      trackEvent(ANALYTICS_EVENTS.WHATS_NEW_SLIDE_VIEWED, {
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
    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_MODAL_OPENED, { source: "modal" });
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
    <Modal isOpen={isModalOpen} onClose={closeModal} size="2xl" backdrop="blur">
      <ModalContent>
        {() => (
          <>
            <ModalHeader>What&apos;s new in GAIA</ModalHeader>

            <ModalBody>
              {isLoading ? (
                <div className="flex h-40 items-center justify-center">
                  <Spinner size="sm" color="primary" />
                </div>
              ) : releases.length === 0 ? (
                <p className="py-8 text-center text-sm text-zinc-500">
                  No releases found.
                </p>
              ) : (
                <div className="overflow-y-auto" style={{ maxHeight: "70vh" }}>
                  {release && (
                    <WhatsNewSlide
                      release={release}
                      isFirst={selectedIndex === 0}
                    />
                  )}
                </div>
              )}
            </ModalBody>

            {showControls && (
              <ModalFooter className="flex items-center justify-between">
                <Button
                  as="a"
                  href={release?.docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  variant="light"
                  size="sm"
                  endContent={<ArrowUpRight01Icon className="h-3.5 w-3.5" />}
                  onPress={() =>
                    release &&
                    trackEvent(ANALYTICS_EVENTS.WHATS_NEW_DOCS_CLICKED, {
                      releaseId: release.id,
                    })
                  }
                >
                  View all release notes
                </Button>
                <div className="flex items-center gap-1">
                  <Button
                    isIconOnly
                    variant="flat"
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
                    variant="flat"
                    size="sm"
                    isDisabled={!canScrollNext}
                    onPress={scrollNext}
                    aria-label="Next release"
                    className="h-7 w-7 min-w-7 bg-zinc-800 text-zinc-400 hover:text-white disabled:opacity-30"
                  >
                    <ArrowRight02Icon className="h-4 w-4" />
                  </Button>
                </div>
              </ModalFooter>
            )}
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
