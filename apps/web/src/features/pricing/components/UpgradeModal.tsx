"use client";

import { Modal, ModalContent } from "@heroui/modal";
import { Tag01Icon } from "@icons";

import { useUpgradeModal } from "../hooks/useUpgradeModal";
import { UpgradeModalOffer, UpgradeModalPlanPicker } from "./UpgradeModalModes";

interface DiscountBannerProps {
  discountCode: string | null | undefined;
  discountPercent: number | null | undefined;
}

export function DiscountBanner({
  discountCode,
  discountPercent,
}: DiscountBannerProps) {
  if (!discountCode) return null;

  return (
    <div className="flex items-center gap-2.5 rounded-2xl bg-success/10 px-4 py-2.5 text-success">
      <Tag01Icon width={18} height={18} aria-hidden />
      <p className="text-sm font-normal">
        {discountPercent ? (
          <>
            <span className="font-semibold">{discountPercent}% off</span> is
            applied with <span className="font-semibold">{discountCode}</span>.
            The prices below are yours.
          </>
        ) : (
          <>
            Use code <span className="font-semibold">{discountCode}</span> at
            checkout.
          </>
        )}
      </p>
    </div>
  );
}

/**
 * The one Pro upsell surface, in both of its modes (see `upgradeModalStore`).
 *
 * Enforcement mode is a compact, undismissable wall around a single monthly
 * Pro CTA — the user cannot proceed, so a plan picker would only be noise.
 * Voluntary mode is the full plan picker (monthly/yearly tabs + cards), since
 * a user who opened this themselves is here to choose.
 */
export function UpgradeModal() {
  const {
    open,
    offerMessage,
    discountCode,
    discountPercent,
    dismissible,
    closeModal,
    plans,
    proPlan,
    copy,
    isConfirming,
    checkoutPhase,
    handleSubscribe,
    logout,
    isOnboardingRoute,
  } = useUpgradeModal();

  if (isOnboardingRoute) return null;

  const discountBanner = (
    <DiscountBanner
      discountCode={discountCode}
      discountPercent={discountPercent}
    />
  );

  return (
    <Modal
      size={dismissible ? "full" : "xl"}
      radius="lg"
      isOpen={open}
      onOpenChange={(isOpen) => {
        if (!isOpen) closeModal();
      }}
      isDismissable={dismissible}
      isKeyboardDismissDisabled={!dismissible}
      hideCloseButton={!dismissible}
      backdrop="blur"
      scrollBehavior="inside"
      className="outline-none"
      classNames={{
        wrapper: dismissible ? "overflow-hidden" : undefined,
        closeButton:
          "text-zinc-400 hover:text-white hover:bg-zinc-800 top-3 right-3",
      }}
    >
      <ModalContent className={dismissible ? undefined : "p-4"}>
        {dismissible ? (
          <UpgradeModalPlanPicker
            offerMessage={offerMessage}
            discountBanner={discountBanner}
            plans={plans}
          />
        ) : (
          <UpgradeModalOffer
            offerMessage={offerMessage}
            discountBanner={discountBanner}
            copy={copy}
            proPlan={proPlan}
            isConfirming={isConfirming}
            checkoutPhase={checkoutPhase}
            onSubscribe={handleSubscribe}
            onLogout={logout}
          />
        )}
      </ModalContent>
    </Modal>
  );
}
