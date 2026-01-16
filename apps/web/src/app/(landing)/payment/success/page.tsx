"use client";

import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";
import { Spinner } from "@heroui/spinner";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SubscriptionSuccessModal } from "@/features/pricing/components/SubscriptionSuccessModal";
import { usePricing } from "@/features/pricing/hooks/usePricing";

export default function PaymentSuccessPage() {
  const router = useRouter();
  const { verifyPayment } = usePricing();

  const [isVerifying, setIsVerifying] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showSuccessModal, setShowSuccessModal] = useState(false);

  useEffect(() => {
    // Set page title
    document.title = "Payment Successful | GAIA";

    const verifyPaymentStatus = async () => {
      try {
        const result = await verifyPayment();

        if (result.payment_completed) {
          setShowSuccessModal(true);
          toast.success("Payment completed successfully!");
        } else {
          setError("Payment not completed yet. Please try again in a moment.");
        }
      } catch (error) {
        console.error("Payment verification failed:", error);
        setError("Failed to verify payment. Please contact support.");
      } finally {
        setIsVerifying(false);
      }
    };

    verifyPaymentStatus();
  }, [verifyPayment]);

  const handleSuccessClose = () => {
    setShowSuccessModal(false);
    router.push("/c");
  };

  const handleRetry = () => {
    setIsVerifying(true);
    setError(null);
    window.location.reload();
  };

  if (isVerifying) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Card className="w-full max-w-md">
          <CardBody className="p-8 text-center">
            <Spinner size="lg" className="mb-4" />
            <h1 className="mb-2 text-xl font-semibold">Verifying Payment...</h1>
            <p className="text-foreground-600">
              Please wait while we confirm your payment with Dodo Payments.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Card className="w-full max-w-md">
          <CardBody className="p-8 text-center">
            <div className="mb-4 text-4xl text-red-500">❌</div>
            <h1 className="mb-2 text-xl font-semibold text-red-600">
              Payment Verification Failed
            </h1>
            <p className="mb-6 text-foreground-600">{error}</p>
            <div className="flex gap-3">
              <Button
                color="primary"
                variant="bordered"
                onPress={() => router.push("/pricing")}
                className="flex-1"
              >
                Back to Pricing
              </Button>
              <Button color="primary" onPress={handleRetry} className="flex-1">
                Try Again
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <>
      <div className="flex min-h-screen items-center justify-center">
        <Card className="w-full max-w-md">
          <CardBody className="p-8 text-center">
            <div className="mb-4 text-4xl text-green-500">✅</div>
            <h1 className="mb-2 text-xl font-semibold text-green-600">
              Payment Successful!
            </h1>
            <p className="mb-6 text-foreground-600">
              Your subscription has been activated successfully.
            </p>
            <Button
              color="primary"
              onPress={handleSuccessClose}
              className="w-full"
            >
              Continue to Chat
            </Button>
          </CardBody>
        </Card>
      </div>

      <SubscriptionSuccessModal
        isOpen={showSuccessModal}
        onClose={handleSuccessClose}
        onNavigateToChat={handleSuccessClose}
        planName="Pro Plan"
      />
    </>
  );
}
