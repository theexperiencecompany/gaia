import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Terms of Service",
  description:
    "Review GAIA's Terms of Service to understand your rights, responsibilities, and the terms governing your use of our AI assistant platform and services.",
  path: "/terms",
  keywords: [
    "Terms of Service",
    "User Agreement",
    "Service Terms",
    "Legal Policy",
    "Terms and Conditions",
    "Usage Terms",
  ],
});

const TermsOfService = () => {
  const termsSchema = generateWebPageSchema(
    "Terms of Service",
    "Review GAIA's Terms of Service to understand your rights, responsibilities, and the terms governing your use of our AI assistant platform.",
    "https://heygaia.io/terms",
    [
      { name: "Home", url: siteConfig.url },
      { name: "Terms of Service", url: `${siteConfig.url}/terms` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Terms of Service", url: `${siteConfig.url}/terms` },
  ]);

  return (
    <>
      <JsonLd data={[termsSchema, breadcrumbSchema]} />
      <div className="flex w-screen flex-col items-center justify-center">
        <div className="privacy-policy max-w-(--breakpoint-xl) p-6 pt-24">
          <h1 className="mb-4 text-3xl font-bold">
            Terms of Service Agreement
          </h1>
          <p className="mb-4 text-sm">Effective Date: July 3, 2025</p>
          <p className="mb-4">
            This Terms of Service Agreement (this "Agreement") is entered into
            by and between GAIA ("Company," "GAIA," "we," "us," or "our"), and
            you, the individual or entity accessing or using our artificial
            intelligence assistant services and platform (the "Service"). BY
            ACCESSING OR USING THE SERVICE, YOU ACKNOWLEDGE THAT YOU HAVE READ,
            UNDERSTOOD, AND AGREE TO BE BOUND BY ALL TERMS AND CONDITIONS OF
            THIS AGREEMENT. IF YOU DO NOT AGREE TO THESE TERMS, YOU MAY NOT
            ACCESS OR USE THE SERVICE.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            1. Acceptance and Binding Agreement
          </h2>
          <p className="mb-4">
            By accessing, browsing, or using the Service, you hereby acknowledge
            your acceptance of this Agreement and agree to be bound by all
            terms, conditions, and notices contained or referenced herein. This
            Agreement constitutes the entire agreement between you and Company
            concerning your use of the Service. You further acknowledge that you
            have read and understood our Privacy Policy, which is incorporated
            herein by reference and forms an integral part of this Agreement.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            2. Eligibility and Capacity
          </h2>
          <p className="mb-4">
            You represent and warrant that: (a) you have the legal capacity and
            authority to enter into this Agreement under the laws of your
            jurisdiction; (b) you are at least eighteen (18) years of age or the
            age of majority in your jurisdiction, whichever is greater; (c) if
            you are entering into this Agreement on behalf of an entity, you
            have the authority to bind such entity; and (d) your use of the
            Service does not violate any applicable laws or regulations.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            3. Account Creation and Security Obligations
          </h2>
          <div className="mb-4">
            <p className="mb-2">You acknowledge and agree that:</p>
            <ul className="ml-6 list-disc">
              <li>
                You shall maintain the strict confidentiality of your account
                credentials, including usernames, passwords, and any other
                access information;
              </li>
              <li>
                You shall provide true, accurate, current, and complete
                information during account registration and shall promptly
                update such information to maintain its accuracy;
              </li>
              <li>
                You bear sole responsibility for all activities that occur under
                your account, whether authorized or unauthorized;
              </li>
              <li>
                You shall immediately notify Company of any unauthorized use of
                your account or any other breach of security;
              </li>
              <li>
                Company shall not be liable for any loss or damage arising from
                your failure to comply with these security obligations.
              </li>
            </ul>
          </div>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            4. Prohibited Uses and Conduct
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              You expressly agree not to use the Service for any purpose that is
              unlawful or prohibited by this Agreement. Prohibited activities
              include, but are not limited to:
            </p>
            <ul className="ml-6 list-disc">
              <li>
                Violating any applicable federal, state, local, or international
                laws, regulations, or ordinances;
              </li>
              <li>
                Transmitting, distributing, or storing any content that is
                defamatory, obscene, threatening, harassing, or otherwise
                objectionable;
              </li>
              <li>
                Engaging in any activity that could disable, overburden, damage,
                or impair the Service or interfere with any other party's use of
                the Service;
              </li>
              <li>
                Attempting to gain unauthorized access to any portion of the
                Service, other accounts, computer systems, or networks;
              </li>
              <li>
                Using automated systems, including robots, spiders, or data
                mining tools, to access or collect information from the Service;
              </li>
              <li>
                Reverse engineering, decompiling, disassembling, or attempting
                to derive the source code of the Service;
              </li>
              <li>
                Circumventing or attempting to circumvent any security measures
                or access controls.
              </li>
            </ul>
          </div>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            5. Service Offerings and Payment Terms
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              Company may offer certain features of the Service without charge
              ("Free Features") and other features that require payment
              ("Premium Features"). With respect to Premium Features:
            </p>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              5.1 Payment and Billing
            </h3>
            <ul className="mb-4 ml-6 list-disc">
              <li>
                All fees are stated in United States dollars and are charged in
                advance for subscription services;
              </li>
              <li>
                Payment is due immediately upon subscription or purchase, and
                recurring fees are automatically charged according to your
                selected billing cycle;
              </li>
              <li>
                You authorize Company to charge your designated payment method
                for all applicable fees, taxes, and other charges;
              </li>
              <li>
                Company reserves the right to change fees upon thirty (30) days'
                prior written notice;
              </li>
              <li>
                Failure to pay applicable fees may result in suspension or
                termination of access to Premium Features.
              </li>
            </ul>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              5.2 Refund Policy
            </h3>
            <div className="mb-4">
              <p className="mb-2">
                ALL SALES ARE FINAL. Company does not provide refunds for any
                payments made for Premium Features, subscriptions, or other
                services, except as expressly stated below or as required by
                applicable law:
              </p>
              <ul className="mb-4 ml-6 list-disc">
                <li>
                  <strong>No Refunds Policy:</strong> All fees paid are
                  non-refundable, including but not limited to subscription
                  fees, one-time purchases, and add-on services;
                </li>
                <li>
                  <strong>Exceptional Circumstances:</strong> Refunds may be
                  considered solely at Company's discretion in cases of
                  technical errors, duplicate charges, or other exceptional
                  circumstances;
                </li>
                <li>
                  <strong>Legal Requirements:</strong> Where required by
                  applicable consumer protection laws, refunds will be provided
                  in accordance with such legal requirements;
                </li>
                <li>
                  <strong>Refund Requests:</strong> Any refund requests must be
                  submitted to support@heygaia.so within thirty (30) days of the
                  original charge and will be reviewed on a case-by-case basis.
                </li>
              </ul>
            </div>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              5.3 Cancellation Policy
            </h3>
            <div className="mb-4">
              <p className="mb-2">
                You may cancel your subscription or Premium Features at any time
                through the following methods:
              </p>
              <ul className="mb-4 ml-6 list-disc">
                <li>
                  <strong>Self-Service Cancellation:</strong> Use the
                  cancellation functionality provided in your account settings
                  or user interface, if available;
                </li>
                <li>
                  <strong>Support Cancellation:</strong> Contact our support
                  team at support@heygaia.so with your cancellation request;
                </li>
                <li>
                  <strong>Cancellation Timing:</strong> Cancellations are
                  effective at the end of your current billing cycle, and you
                  will retain access to Premium Features until that time;
                </li>
                <li>
                  <strong>No Partial Refunds:</strong> Cancellation does not
                  entitle you to a refund for the current billing period or any
                  unused portion thereof;
                </li>
                <li>
                  <strong>Reactivation:</strong> You may reactivate your
                  subscription at any time, subject to the then-current pricing
                  and terms.
                </li>
              </ul>
            </div>

            <h3 className="mt-4 mb-2 text-lg font-semibold">
              5.4 Free Trial and Promotional Offers
            </h3>
            <div className="mb-4">
              <p className="mb-2">
                If Company offers free trials or promotional pricing:
              </p>
              <ul className="ml-6 list-disc">
                <li>
                  Free trials automatically convert to paid subscriptions unless
                  cancelled before the trial period ends;
                </li>
                <li>
                  You must provide valid payment information to access free
                  trials;
                </li>
                <li>
                  Promotional offers are subject to additional terms and
                  conditions that will be provided at the time of the offer;
                </li>
                <li>
                  Company reserves the right to modify or discontinue free
                  trials and promotional offers at any time.
                </li>
              </ul>
            </div>
          </div>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            6. Intellectual Property Rights
          </h2>
          <p className="mb-4">
            All content, features, and functionality of the Service, including
            but not limited to text, graphics, logos, button icons, images,
            audio clips, data compilations, software, and the compilation
            thereof (collectively, the "Company Content"), are and shall remain
            the exclusive property of Company and its licensors and are
            protected by United States and international copyright, trademark,
            patent, trade secret, and other intellectual property laws. You are
            granted a limited, non-exclusive, non-transferable, revocable
            license to access and use the Company Content solely for your
            personal, non-commercial use in accordance with this Agreement.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            7. User-Generated Content and License Grant
          </h2>
          <p className="mb-4">
            You retain all ownership rights in any content, data, or information
            you submit to the Service ("User Content"). By submitting User
            Content, you hereby grant Company a worldwide, non-exclusive,
            royalty-free, sublicensable, and transferable license to use,
            reproduce, distribute, prepare derivative works of, display, and
            perform the User Content solely in connection with the Service and
            Company's business operations. You represent and warrant that you
            have all necessary rights to grant this license and that your User
            Content does not infringe upon any third-party rights.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            8. Privacy and Data Protection
          </h2>
          <p className="mb-4">
            Company's collection, use, and disclosure of personal information is
            governed by our Privacy Policy, which is incorporated herein by
            reference. Company hereby represents that it does not and will not
            sell, rent, or lease any personal data to third parties. Company
            processes personal data solely for the purposes of providing the
            Service and as otherwise described in the Privacy Policy.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">9. Termination</h2>
          <p className="mb-4">
            Either party may terminate this Agreement at any time with or
            without cause. Company may immediately terminate or suspend your
            access to the Service without prior notice if Company determines, in
            its sole discretion, that you have violated any provision of this
            Agreement. Upon termination, your right to use the Service shall
            immediately cease, and you shall discontinue all use of the Service.
            Sections 6, 7, 9, 10, 11, 12, and 13 shall survive termination of
            this Agreement.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            10. Disclaimers of Warranties
          </h2>
          <div className="mb-4">
            <p className="mb-2">
              THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS.
              COMPANY HEREBY DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED,
              INCLUDING BUT NOT LIMITED TO:
            </p>
            <ul className="ml-6 list-disc">
              <li>
                IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
                PURPOSE, AND NON-INFRINGEMENT;
              </li>
              <li>
                WARRANTIES THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE,
                OR SECURE;
              </li>
              <li>
                WARRANTIES REGARDING THE ACCURACY, RELIABILITY, OR COMPLETENESS
                OF ANY CONTENT OR INFORMATION PROVIDED THROUGH THE SERVICE.
              </li>
            </ul>
            <p className="mt-2">
              NO ADVICE OR INFORMATION, WHETHER ORAL OR WRITTEN, OBTAINED BY YOU
              FROM COMPANY OR THROUGH THE SERVICE SHALL CREATE ANY WARRANTY NOT
              EXPRESSLY STATED IN THIS AGREEMENT.
            </p>
          </div>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            11. Limitation of Liability
          </h2>
          <p className="mb-4">
            TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL
            COMPANY, ITS OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, OR AFFILIATES
            BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR
            PUNITIVE DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF PROFITS,
            DATA, USE, GOODWILL, OR OTHER INTANGIBLE LOSSES, ARISING OUT OF OR
            RELATING TO YOUR USE OF THE SERVICE, REGARDLESS OF THE THEORY OF
            LIABILITY (CONTRACT, TORT, OR OTHERWISE) AND EVEN IF COMPANY HAS
            BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. COMPANY'S TOTAL
            LIABILITY FOR ANY CLAIM ARISING OUT OF OR RELATING TO THIS AGREEMENT
            SHALL NOT EXCEED THE AMOUNT YOU PAID TO COMPANY FOR THE SERVICE
            DURING THE TWELVE (12) MONTHS PRECEDING THE CLAIM.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            12. Indemnification
          </h2>
          <p className="mb-4">
            You agree to defend, indemnify, and hold harmless Company and its
            officers, directors, employees, agents, and affiliates from and
            against any and all claims, damages, obligations, losses,
            liabilities, costs, and expenses (including reasonable attorneys'
            fees) arising from: (a) your use of the Service; (b) your violation
            of this Agreement; (c) your violation of any third-party rights; or
            (d) any content you submit to the Service.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            13. Modifications to Terms
          </h2>
          <p className="mb-4">
            Company reserves the right to modify this Agreement at any time by
            posting revised terms on the Service. Material changes will be
            communicated via email or prominent notice on the Service at least
            thirty (30) days before taking effect. Your continued use of the
            Service after the effective date of any modifications constitutes
            your acceptance of the revised Agreement. If you do not agree to the
            modifications, you must discontinue use of the Service.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            14. Governing Law and Dispute Resolution
          </h2>
          <p className="mb-4">
            This Agreement shall be governed by and construed in accordance with
            the laws of the jurisdiction where Company is established, without
            regard to its conflict of law principles. Any dispute arising out of
            or relating to this Agreement shall be resolved through binding
            arbitration administered by a recognized arbitration association in
            accordance with its commercial arbitration rules, and judgment on
            the arbitration award may be entered in any court having
            jurisdiction.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            15. Severability and Waiver
          </h2>
          <p className="mb-4">
            If any provision of this Agreement is held to be invalid or
            unenforceable, the remaining provisions shall remain in full force
            and effect. The failure of Company to enforce any provision of this
            Agreement shall not constitute a waiver of such provision or any
            other provision.
          </p>

          <h2 className="mt-6 mb-2 text-xl font-semibold">
            16. Contact Information
          </h2>
          <p>
            For any questions, concerns, or notices regarding this Agreement,
            please contact us at:
            <br />
            Email:{" "}
            <a
              className="text-blue-500 underline"
              href="mailto:support@heygaia.so"
            >
              support@heygaia.so
            </a>
          </p>
        </div>
      </div>
    </>
  );
};

export default TermsOfService;
