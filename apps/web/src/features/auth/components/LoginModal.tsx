"use client";

import { Button, Modal, Spinner } from "@heroui/react";
import { Alert01Icon, Login02Icon } from "@icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import {
  useLoginModal,
  useLoginModalActions,
} from "@/features/auth/hooks/useLoginModal";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { usePathname, useRouter } from "@/i18n/navigation";
import { track } from "@/lib/analytics";
import { isSelfhostWeb } from "@/lib/selfhost";

// Routes where login modal should NOT be dismissable (main app routes that require auth)
const NON_DISMISSABLE_ROUTE_PREFIXES = [
  "/c",
  "/integrations",
  "/workflows",
  "/todos",
  "/onboarding",
  "/settings",
  "/pins",
  "/redirect",
  "/calendar",
  "/dashboard",
];

const isNonDismissableRoute = (pathname: string): boolean => {
  return NON_DISMISSABLE_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
};

export default function LoginModal() {
  const isOpen = useLoginModal();
  const { setLoginModalOpen } = useLoginModalActions();
  const pathname = usePathname();

  if (pathname === "/login" || pathname === "/signup") return null;

  // Allow dismissing everywhere EXCEPT main app routes (which require auth)
  const canDismiss = !isNonDismissableRoute(pathname);

  return (
    <Modal isOpen={isOpen} onOpenChange={(v) => setLoginModalOpen(v)}>
      <Modal.Backdrop
        isDismissable={canDismiss}
        isKeyboardDismissDisabled={!canDismiss}
        variant="blur"
      >
        <Modal.Container placement="center" size="md">
          <Modal.Dialog className="p-4 outline-none" aria-label="Login">
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Body>
              <div className="mb-3 space-y-3 text-center">
                <div className="text-5xl font-medium">Login</div>
                <div className="text-medium text-foreground-600">
                  Please login to continue your journey with GAIA.
                </div>
              </div>
              {isSelfhostWeb() ? (
                <InstanceSignIn
                  onLocalSignIn={() => setLoginModalOpen(false)}
                />
              ) : (
                <SignInButton isLocalAuth={false} />
              )}
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

/**
 * A self-host instance's sign-in, by the auth mode it reports: local auth has
 * no WorkOS routes, so Sign in goes to /login. Read only while the modal is
 * open; an unreadable status offers a retry, never a WorkOS button.
 */
function InstanceSignIn({ onLocalSignIn }: { onLocalSignIn: () => void }) {
  const { data, isError, isFetching, refetch } = useSetupStatus();

  if (data) {
    return (
      <SignInButton
        isLocalAuth={data.auth_mode === "local"}
        onLocalSignIn={onLocalSignIn}
      />
    );
  }
  if (!isError) return <Spinner className="mx-auto" />;
  return (
    <div className="flex flex-col items-center gap-3 text-center">
      <Alert01Icon size={22} className="text-zinc-500" />
      <p className="text-sm text-zinc-400">
        Couldn&apos;t reach your GAIA server to start signing in.
      </p>
      <Button
        variant="tertiary"
        isPending={isFetching}
        onPress={() => {
          void refetch();
        }}
      >
        Try again
      </Button>
    </div>
  );
}

interface SignInButtonProps {
  isLocalAuth: boolean;
  onLocalSignIn?: () => void;
}

function SignInButton({ isLocalAuth, onLocalSignIn }: SignInButtonProps) {
  const router = useRouter();
  return (
    <RaisedButton
      color="#00bbff"
      className="text-medium w-full"
      onClick={() => {
        track("navigation:cta_clicked", {
          location: "login_modal",
          destination: isLocalAuth ? "/login" : "workos_oauth",
        });
        if (isLocalAuth) {
          onLocalSignIn?.();
          router.push("/login");
        } else {
          handleAuthLogin();
        }
      }}
    >
      <Login02Icon width={22} height={22} />
      Sign in
    </RaisedButton>
  );
}
