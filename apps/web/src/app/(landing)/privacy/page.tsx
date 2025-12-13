import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Privacy Policy",
  description:
    "Review GAIA's Privacy Policy to learn how we collect, use, and protect your personal data while providing our AI assistant services. We prioritize your privacy and data security.",
  path: "/privacy",
  keywords: [
    "Privacy Policy",
    "Data Protection",
    "Personal Data",
    "Privacy",
    "Data Security",
    "GDPR",
    "Data Privacy",
  ],
});

const PrivacyPolicy = () => {
  const privacySchema = generateWebPageSchema(
    "Privacy Policy",
    "Review GAIA's Privacy Policy to learn how we collect, use, and protect your personal data.",
    "https://heygaia.io/privacy",
    [
      { name: "Home", url: siteConfig.url },
      { name: "Privacy Policy", url: `${siteConfig.url}/privacy` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Privacy Policy", url: `${siteConfig.url}/privacy` },
  ]);

  return (
    <>
      <JsonLd data={[privacySchema, breadcrumbSchema]} />
      <div className="flex w-screen flex-col items-center justify-center">
        <div className="privacy-policy max-w-(--breakpoint-xl) p-6 pt-24">
          <h1 className="mb-4 text-2xl font-bold">Privacy Policy</h1>
          <p className="mb-4">
            <strong>Effective Date:</strong> July 3, 2025
          </p>
          <p className="mb-4">
            This Privacy Policy (this "Policy") describes how GAIA ("Company,"
            "GAIA," "we," "us," or "our") collects, uses, stores, processes, and
            discloses personal information in connection with our artificial
            intelligence assistant services and platform (the "Service"). This
            Policy applies to all users of the Service and is incorporated by
            reference into our Terms of Service Agreement. BY USING THE SERVICE,
            YOU CONSENT TO THE COLLECTION, USE, AND DISCLOSURE OF YOUR PERSONAL
            INFORMATION AS DESCRIBED IN THIS POLICY.
          </p>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            1. Information We Collect
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              We collect several categories of personal information about you
              through various means:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              1.1 Information You Provide Directly
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                <strong>Account Information:</strong> Name, email address,
                username, password, and other registration information you
                provide when creating an account;
              </li>
              <li>
                <strong>Payment Information:</strong> Credit card numbers,
                billing addresses, and other payment-related information
                processed through our third-party payment processors;
              </li>
              <li>
                <strong>Profile Information:</strong> Optional profile
                information, preferences, and settings you choose to provide;
              </li>
              <li>
                <strong>Communication Data:</strong> Information you provide
                when you contact us for support, feedback, or other
                communications;
              </li>
              <li>
                <strong>User Content:</strong> All text, files, images, audio,
                and other content you submit to or through the Service.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              1.2 Information We Collect Automatically
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                <strong>Device Information:</strong> IP address, device type,
                operating system, browser type and version, device identifiers,
                and mobile network information;
              </li>
              <li>
                <strong>Usage Data:</strong> Information about how you use the
                Service, including features accessed, time spent, interaction
                patterns, and performance metrics;
              </li>
              <li>
                <strong>Location Data:</strong> General location information
                derived from your IP address (not precise geolocation unless
                explicitly consented);
              </li>
              <li>
                <strong>Cookies and Tracking Technologies:</strong> Information
                collected through cookies, web beacons, pixels, and similar
                tracking technologies.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              1.3 Information from Third Parties
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                <strong>Authentication Services:</strong> If you use third-party
                authentication services (e.g., Google, GitHub), we may receive
                basic profile information such as your name, email address, and
                profile picture;
              </li>
              <li>
                <strong>Google User Data:</strong> When you connect Google
                services, we may access and collect data from your Google
                account including but not limited to email, calendar events,
                contacts, and documents as authorized by you through Google's
                OAuth consent process;
              </li>
              <li>
                <strong>Analytics Providers:</strong> Information from
                third-party analytics services that help us understand Service
                usage and performance;
              </li>
              <li>
                <strong>Security Services:</strong> Information from fraud
                prevention and security services to protect against unauthorized
                access.
              </li>
            </ul>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            2. How We Use Your Information
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              We use your personal information for the following purposes:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              2.1 Service Provision and Operation
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Providing, maintaining, and improving the Service and its
                features;
              </li>
              <li>
                Processing and responding to your requests and interactions with
                the AI assistant;
              </li>
              <li>
                <strong>Google User Data Processing:</strong> Using Google user
                data solely to provide and improve our AI assistant
                functionality, including processing emails, calendar events, and
                documents to provide relevant assistance and responses;
              </li>
              <li>
                Personalizing your experience and delivering relevant content
                and recommendations;
              </li>
              <li>
                Processing payments and managing your account and subscriptions.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              2.2 Communication and Support
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Responding to your inquiries, comments, and support requests;
              </li>
              <li>
                Sending you service-related communications, updates, and
                notifications;
              </li>
              <li>Providing customer support and technical assistance;</li>
              <li>
                Conducting surveys and gathering feedback to improve our
                services.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              2.3 Analytics and Improvement
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Analyzing usage patterns to understand how the Service is used
                and to improve functionality;
              </li>
              <li>
                Conducting research and analytics to enhance our AI models and
                algorithms;
              </li>
              <li>
                Monitoring and analyzing trends, usage, and activities in
                connection with the Service;
              </li>
              <li>Developing new features, services, and products.</li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              2.4 Security and Legal Compliance
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Protecting against fraud, unauthorized access, and other
                security threats;
              </li>
              <li>
                Investigating and preventing violations of our Terms of Service;
              </li>
              <li>
                Complying with applicable laws, regulations, and legal
                obligations;
              </li>
              <li>
                Enforcing our rights and protecting our property and interests.
              </li>
            </ul>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            3. Data Sharing and Disclosure
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              We do not sell, rent, or lease your personal information to third
              parties.{" "}
              <strong>We do not sell Google user data to third parties.</strong>{" "}
              However, we may share your information in the following limited
              circumstances:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              3.1 Service Providers
            </h3>
            <p className="mb-2">
              We may share your information with trusted third-party service
              providers who assist us in operating our business, including:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>Cloud hosting and infrastructure providers;</li>
              <li>Payment processing companies;</li>
              <li>Customer support and communication platforms;</li>
              <li>Analytics and monitoring services;</li>
              <li>Security and fraud prevention services.</li>
            </ul>
            <p className="mb-2">
              <strong>Google User Data:</strong> We only share Google user data
              with service providers who are necessary for providing our AI
              assistant functionality and who have agreed to appropriate data
              protection measures. We do not transfer Google user data to third
              parties for advertising or other unrelated purposes.
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              3.2 Legal Requirements
            </h3>
            <p className="mb-2">
              We may disclose your information when required by law or when we
              believe in good faith that disclosure is necessary to:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Comply with a legal obligation, court order, or government
                request;
              </li>
              <li>Protect and defend our rights or property;</li>
              <li>
                Prevent or investigate possible wrongdoing in connection with
                the Service;
              </li>
              <li>
                Protect the personal safety of users of the Service or the
                public.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              3.3 Business Transfers
            </h3>
            <p className="mb-4">
              In the event of a merger, acquisition, or sale of all or a portion
              of our assets, your information may be transferred to the
              acquiring entity, subject to the same privacy protections outlined
              in this Policy.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            4. Cookies and Tracking Technologies
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              We use cookies and similar tracking technologies to collect
              information about your use of the Service. These technologies
              include:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              4.1 Types of Cookies
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                <strong>Essential Cookies:</strong> Required for basic Service
                functionality and cannot be disabled;
              </li>
              <li>
                <strong>Analytics Cookies:</strong> Help us understand how you
                use the Service and improve its performance;
              </li>
              <li>
                <strong>Preference Cookies:</strong> Remember your settings and
                preferences for a better user experience;
              </li>
              <li>
                <strong>Third-Party Cookies:</strong> Placed by our service
                providers for analytics and security purposes.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              4.2 Cookie Management
            </h3>
            <p className="mb-4">
              You can control cookies through your browser settings. However,
              disabling certain cookies may limit your ability to use some
              features of the Service. For more information about managing
              cookies, please refer to your browser's help documentation.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">5. Data Security</h2>
          <div className="mb-4">
            <p className="mb-2">
              We implement appropriate technical and organizational measures to
              protect your personal information against unauthorized access,
              alteration, disclosure, or destruction. These measures include:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Encryption of data in transit and at rest using
                industry-standard protocols;
              </li>
              <li>
                Access controls and authentication mechanisms to limit access to
                personal information;
              </li>
              <li>
                Regular security assessments and monitoring of our systems;
              </li>
              <li>
                Employee training on data privacy and security best practices;
              </li>
              <li>
                Incident response procedures to address potential security
                breaches.
              </li>
              <li>
                <strong>Google User Data Protection:</strong> Enhanced security
                measures for Google user data including restricted access on a
                need-to-know basis, secure API connections, and compliance with
                Google's security requirements.
              </li>
            </ul>
            <p className="mb-4">
              However, no method of transmission over the internet or electronic
              storage is 100% secure. While we strive to protect your personal
              information, we cannot guarantee its absolute security.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            6. Your Rights and Choices
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              Depending on your location, you may have certain rights regarding
              your personal information:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              6.1 Access and Portability
            </h3>
            <p className="mb-2">You have the right to:</p>
            <ul className="mb-4 ml-6 list-disc">
              <li>Access the personal information we hold about you;</li>
              <li>
                Receive a copy of your personal information in a structured,
                commonly used format;
              </li>
              <li>Request information about how we use and share your data.</li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              6.2 Correction and Deletion
            </h3>
            <p className="mb-2">You have the right to:</p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Correct or update inaccurate or incomplete personal information;
              </li>
              <li>
                Request deletion of your personal information in certain
                circumstances;
              </li>
              <li>
                Withdraw consent where our processing is based on your consent.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              6.3 Restriction and Objection
            </h3>
            <p className="mb-2">You have the right to:</p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Restrict the processing of your personal information in certain
                circumstances;
              </li>
              <li>Object to processing based on our legitimate interests;</li>
              <li>Opt-out of marketing communications.</li>
            </ul>

            <p className="mb-4">
              To exercise these rights, please contact us using the information
              provided in Section 10.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">7. Data Retention</h2>
          <div className="mb-4">
            <p className="mb-2">
              We retain your personal information only for as long as necessary
              to fulfill the purposes for which it was collected, including:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Account information: Retained while your account is active and
                for a reasonable period after closure;
              </li>
              <li>
                Usage data: Typically retained for up to 24 months for analytics
                and improvement purposes;
              </li>
              <li>
                Payment information: Retained as required by law and for
                legitimate business purposes;
              </li>
              <li>
                Support communications: Retained for up to 3 years for quality
                assurance and legal compliance.
              </li>
              <li>
                <strong>Google User Data:</strong> Retained only as long as
                necessary to provide our services or as required by law. You can
                request deletion of your Google user data at any time through
                your account settings or by contacting us directly.
              </li>
            </ul>
            <p className="mb-4">
              We may retain certain information for longer periods when required
              by law or for legitimate business purposes such as fraud
              prevention and security.{" "}
              <strong>
                Google user data is deleted when no longer necessary for
                providing our AI assistant services.
              </strong>
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            8. International Data Transfers
          </h2>
          <div className="mb-4">
            <p className="mb-4">
              Your personal information may be transferred to and processed in
              countries other than your country of residence. These countries
              may have different data protection laws than your country. When we
              transfer your information internationally, we implement
              appropriate safeguards to protect your information, including:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Standard contractual clauses approved by relevant data
                protection authorities;
              </li>
              <li>
                Adequacy decisions confirming that the destination country
                provides adequate protection;
              </li>
              <li>
                Other appropriate safeguards as required by applicable law.
              </li>
            </ul>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            9. Third-Party Services and Links
          </h2>
          <div className="mb-4">
            <p className="mb-4">
              The Service may contain links to or integrate with third-party
              websites, applications, or services. This Privacy Policy does not
              apply to these third-party services. We encourage you to review
              the privacy policies of any third-party services you use in
              connection with our Service.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            10. Changes to This Privacy Policy
          </h2>
          <div className="mb-4">
            <p className="mb-4">
              We may update this Privacy Policy from time to time to reflect
              changes in our practices or applicable laws. When we make material
              changes, we will:
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>Post the updated Policy on our website;</li>
              <li>Update the "Effective Date" at the top of this Policy;</li>
              <li>
                Provide notice through the Service or via email for significant
                changes;
              </li>
              <li>Obtain your consent where required by applicable law.</li>
            </ul>
            <p className="mb-4">
              Your continued use of the Service after any changes become
              effective constitutes your acceptance of the updated Policy.
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            11. Contact Information
          </h2>
          <div className="mb-4">
            <p className="mb-4">
              If you have any questions, concerns, or requests regarding this
              Privacy Policy or our data practices, please contact us at:
            </p>
            <p className="mb-4">
              Email:{" "}
              <a
                className="text-blue-500 underline"
                href="mailto:support@heygaia.so"
              >
                support@heygaia.so
              </a>
            </p>
          </div>

          <h2 className="mt-4 mb-2 text-xl font-semibold">
            12. Jurisdiction-Specific Provisions
          </h2>
          <div className="mb-4">
            <h3 className="mt-4 mb-2 text-lg font-semibold">
              12.1 California Residents
            </h3>
            <p className="mb-2">
              If you are a California resident, you have additional rights under
              the California Consumer Privacy Act (CCPA):
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Right to know what personal information is collected and how it
                is used;
              </li>
              <li>Right to request deletion of personal information;</li>
              <li>
                Right to opt-out of the sale of personal information (we do not
                sell personal information);
              </li>
              <li>
                Right to non-discrimination for exercising your privacy rights.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              12.2 European Economic Area (EEA) Residents
            </h3>
            <p className="mb-2">
              If you are located in the EEA, you have additional rights under
              the General Data Protection Regulation (GDPR):
            </p>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                Legal basis for processing: We process your data based on
                consent, contract performance, legitimate interests, or legal
                obligations;
              </li>
              <li>
                Right to lodge a complaint with your local data protection
                authority;
              </li>
              <li>Right to data portability in machine-readable format;</li>
              <li>
                Enhanced rights regarding automated decision-making and
                profiling.
              </li>
            </ul>
          </div>
        </div>
      </div>
    </>
  );
};

export default PrivacyPolicy;
