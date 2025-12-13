import { parseEmail } from "@/features/mail/utils/mailUtils";

export const EmailFrom = ({ from }: { from: string }) => {
  const { name, email } = parseEmail(from);
  return <>{name ? name : email}</>;
};
