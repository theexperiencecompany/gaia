import { Card } from "heroui-native";
import type { ReactNode } from "react";

interface AuthCardProps {
  children: ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  return (
    <Card
      variant="secondary"
      animation="disable-all"
      className="w-full max-w-[450px] rounded-[20px] px-8 py-10"
    >
      <Card.Body className="p-0">{children}</Card.Body>
    </Card>
  );
}
