import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { FeatureDetailClient } from "@/features/landing/components/features/FeatureDetailClient";
import {
  FEATURES,
  getFeatureBySlug,
} from "@/features/landing/data/featuresData";

interface Props {
  params: Promise<{ slug: string; locale: string }>;
}

export async function generateStaticParams() {
  return FEATURES.map((f) => ({ slug: f.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const feature = getFeatureBySlug(slug);
  if (!feature) return {};
  return {
    title: `${feature.title} — GAIA`,
    description: feature.subheadline,
  };
}

export default async function FeatureDetailPage({ params }: Props) {
  const { slug } = await params;
  const feature = getFeatureBySlug(slug);
  if (!feature) notFound();
  return <FeatureDetailClient feature={feature!} />;
}
