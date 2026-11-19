import { LinkUnavailable } from "@/features/short-links/components/LinkUnavailable";

export default function ShortLinkNotFound() {
  return <LinkUnavailable state={{ denial: "link_not_found" }} />;
}
