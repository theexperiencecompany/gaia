import type { Metadata } from "next";

import ContactForm from "@/features/contact/components/ContactForm";
import ContactSidebar from "@/features/contact/components/ContactSidebar";
import { generateContactPageSchema, generatePageMetadata } from "@/lib/seo";

const title = "Contact Us";
const description =
  "Get in touch with the GAIA team for support, feature requests, partnerships, or general inquiries. We're here to help you maximize your productivity with AI.";

export const metadata: Metadata = generatePageMetadata({
  title,
  description,
  path: "/contact",
  keywords: [
    "Contact GAIA",
    "Customer Support",
    "AI Assistant Help",
    "Technical Support",
    "Feature Requests",
    "Partnerships",
  ],
});

export default function ContactPage() {
  const contactSchema = generateContactPageSchema();

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(contactSchema) }}
      />
      <main className="flex h-screen w-screen flex-col items-center justify-center bg-gradient-to-b from-zinc-900 to-black px-6 py-16">
        <header className="text-center">
          <h1 className="font-serif text-8xl font-light tracking-tight text-balance">
            Contact us
          </h1>
          <p className="mt-3 text-foreground-500">
            Get in touch with our team for support, feature requests, or general
            inquiries.
          </p>
        </header>

        <section className="mt-16 grid w-full max-w-5xl gap-10 md:grid-cols-[250px_1fr]">
          <aside className="border-zinc-800 md:border-r md:pr-10">
            <ContactSidebar />
          </aside>

          <section>
            <h2 id="inquiries-heading" className="mb-4 text-lg font-medium">
              Send us a message
            </h2>
            <ContactForm aria-labelledby="inquiries-heading" />
          </section>
        </section>
      </main>
    </>
  );
}
