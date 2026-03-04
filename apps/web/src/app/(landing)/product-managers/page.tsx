import type { Metadata } from "next";
import ProductManagerClient from "./ProductManagerClient";

export const metadata: Metadata = {
  title:
    "GAIA for Product Managers — Stop Managing Tools, Start Managing Your Product",
  description:
    "GAIA connects Linear, Slack, GitHub, and Notion — then handles the status updates, meeting prep, and feature triage so you can focus on product strategy.",
};

export default function ProductManagersPage() {
  return <ProductManagerClient />;
}
