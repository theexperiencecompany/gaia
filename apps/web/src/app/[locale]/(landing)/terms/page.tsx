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

function TermsIntro() {
  return (
    <>
      <h1 className="mb-4 text-3xl font-bold">Terms of Service Agreement</h1>
      <p className="mb-4 text-sm">Effective Date: August 14, 2026</p>
      <p className="mb-4">
        This Terms of Service Agreement (this "Agreement") is entered into by
        and between The Experience Company, Inc., a Delaware corporation
        ("Company," "GAIA," "we," "us," or "our"), and you, the individual or
        entity accessing or using our artificial intelligence assistant services
        and platform (the "Service"). BY ACCESSING OR USING THE SERVICE, YOU
        ACKNOWLEDGE THAT YOU HAVE READ, UNDERSTOOD, AND AGREE TO BE BOUND BY ALL
        TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE TO THESE
        TERMS, YOU MAY NOT ACCESS OR USE THE SERVICE.
      </p>
      <p className="mb-4">
        <strong>
          SECTION 18 CONTAINS A BINDING ARBITRATION AGREEMENT AND A CLASS ACTION
          WAIVER. THEY AFFECT HOW DISPUTES BETWEEN YOU AND COMPANY ARE RESOLVED.
          YOU MAY OPT OUT OF ARBITRATION WITHIN THIRTY (30) DAYS AS DESCRIBED IN
          SECTION 18.5.
        </strong>
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        1. Acceptance and Binding Agreement
      </h2>
      <p className="mb-4">
        By accessing, browsing, or using the Service, you hereby acknowledge
        your acceptance of this Agreement and agree to be bound by all terms,
        conditions, and notices contained or referenced herein. This Agreement
        constitutes the entire agreement between you and Company concerning your
        use of the Service. You further acknowledge that you have read and
        understood our Privacy Policy, which is incorporated herein by reference
        and forms an integral part of this Agreement.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        2. Eligibility and Capacity
      </h2>
      <p className="mb-4">
        You represent and warrant that: (a) you have the legal capacity and
        authority to enter into this Agreement under the laws of your
        jurisdiction; (b) you are at least eighteen (18) years of age or the age
        of majority in your jurisdiction, whichever is greater; (c) if you are
        entering into this Agreement on behalf of an entity, you have the
        authority to bind such entity; and (d) your use of the Service does not
        violate any applicable laws or regulations.
      </p>
    </>
  );
}

function TermsAccounts() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        3. Account Creation and Security Obligations
      </h2>
      <div className="mb-4">
        <p className="mb-2">You acknowledge and agree that:</p>
        <ul className="ml-6 list-disc">
          <li>
            You shall maintain the strict confidentiality of your account
            credentials, including usernames, passwords, and any other access
            information;
          </li>
          <li>
            You shall provide true, accurate, current, and complete information
            during account registration and shall promptly update such
            information to maintain its accuracy;
          </li>
          <li>
            You bear sole responsibility for all activities that occur under
            your account, whether authorized or unauthorized;
          </li>
          <li>
            You shall immediately notify Company of any unauthorized use of your
            account or any other breach of security;
          </li>
          <li>
            Company shall not be liable for any loss or damage arising from your
            failure to comply with these security obligations.
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
            Using the Service to generate or distribute spam, bulk unsolicited
            messages, malware, or content designed to deceive or defraud;
          </li>
          <li>
            Engaging in any activity that could disable, overburden, damage, or
            impair the Service or interfere with any other party's use of the
            Service;
          </li>
          <li>
            Attempting to gain unauthorized access to any portion of the
            Service, other accounts, computer systems, or networks;
          </li>
          <li>
            Using automated systems, including robots, spiders, or data mining
            tools, to access or collect information from the Service;
          </li>
          <li>
            Reverse engineering, decompiling, disassembling, or attempting to
            derive the source code of the Service;
          </li>
          <li>
            Circumventing or attempting to circumvent any security measures,
            access controls, or usage limits.
          </li>
        </ul>
      </div>
    </>
  );
}

function TermsPayments() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        5. Service Offerings and Payment Terms
      </h2>
      <div className="mb-4">
        <p className="mb-2">
          Company may offer certain features of the Service without charge
          ("Free Features") and other features that require payment ("Premium
          Features"). With respect to Premium Features:
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          5.1 Payment, Billing, and Automatic Renewal
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            <strong>Merchant of record:</strong> Payments for Premium Features
            are processed by Dodo Payments, which acts as the merchant of record
            and is the seller of record for your purchase. Your purchase is also
            subject to Dodo Payments' terms, and Dodo Payments is responsible
            for collecting and remitting applicable taxes;
          </li>
          <li>
            <strong>Subscriptions renew automatically.</strong> Your
            subscription will automatically renew at the end of each billing
            period, and your payment method will be charged the then-current
            subscription price, until you cancel;
          </li>
          <li>
            The subscription price and billing frequency are disclosed to you on
            the pricing page and at checkout before you complete your purchase;
          </li>
          <li>
            You may cancel at any time from your account settings, as described
            in Section 5.3. Cancelling stops future renewals;
          </li>
          <li>
            Fees are charged in advance for each billing period, and you
            authorize Company and its payment processor to charge your
            designated payment method for all applicable fees, taxes, and other
            charges;
          </li>
          <li>
            Company reserves the right to change fees upon thirty (30) days'
            prior written notice. Price changes take effect at your next
            renewal, and you may cancel before then;
          </li>
          <li>
            Failure to pay applicable fees may result in suspension or
            termination of access to Premium Features.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">5.2 Refund Policy</h3>
        <div className="mb-4">
          <p className="mb-2">
            Except as required by applicable law or as expressly stated below,
            fees paid for Premium Features are non-refundable:
          </p>
          <ul className="mb-4 ml-6 list-disc">
            <li>
              <strong>General Policy:</strong> Fees paid are non-refundable,
              including subscription fees, one-time purchases, and add-on
              services;
            </li>
            <li>
              <strong>Statutory Rights Preserved:</strong> Nothing in this
              Agreement limits any refund, cancellation, or withdrawal right you
              have under applicable consumer protection law. Where such a right
              applies, it prevails over this Section;
            </li>
            <li>
              <strong>Exceptional Circumstances:</strong> Refunds may be granted
              at Company's discretion in cases of technical errors, duplicate
              charges, or other exceptional circumstances;
            </li>
            <li>
              <strong>Refund Requests:</strong> Refund requests should be
              submitted to support@heygaia.so within thirty (30) days of the
              original charge and will be reviewed on a case-by-case basis.
            </li>
          </ul>
        </div>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          5.3 Cancellation Policy
        </h3>
        <div className="mb-4">
          <p className="mb-2">You may cancel your subscription at any time:</p>
          <ul className="mb-4 ml-6 list-disc">
            <li>
              <strong>Self-Service Cancellation:</strong> Cancel directly from
              your account settings. If you signed up online, you can cancel
              online, without contacting us;
            </li>
            <li>
              <strong>Support Cancellation:</strong> Alternatively, contact our
              support team at support@heygaia.so with your cancellation request;
            </li>
            <li>
              <strong>Cancellation Timing:</strong> Cancellations are effective
              at the end of your current billing cycle, and you will retain
              access to Premium Features until that time;
            </li>
            <li>
              <strong>No Partial Refunds:</strong> Except where required by law,
              cancellation does not entitle you to a refund for the current
              billing period or any unused portion thereof;
            </li>
            <li>
              <strong>Reactivation:</strong> You may reactivate your
              subscription at any time, subject to the then-current pricing and
              terms.
            </li>
          </ul>
        </div>
      </div>
    </>
  );
}

function TermsServiceAndContent() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">6. Usage Limits</h2>
      <p className="mb-4">
        The Service is subject to usage limits, which may include limits on
        messages, AI model requests, connected integrations, storage, background
        workflows, and other resources. Applicable limits depend on your plan
        and are described in the Service. Company may set, change, or enforce
        usage limits at any time, including to protect the stability and
        security of the Service or to prevent abuse. Company may throttle,
        suspend, or reduce access where usage materially exceeds normal
        individual use or is inconsistent with your plan.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        7. Intellectual Property and License to Use
      </h2>
      <div className="mb-4">
        <p className="mb-4">
          All content, features, and functionality of the Service, including but
          not limited to text, graphics, logos, button icons, images, audio
          clips, data compilations, software, and the compilation thereof
          (collectively, the "Company Content"), are and shall remain the
          exclusive property of Company and its licensors and are protected by
          United States and international copyright, trademark, patent, trade
          secret, and other intellectual property laws.
        </p>
        <p className="mb-2">
          Subject to your compliance with this Agreement, Company grants you a
          limited, non-exclusive, non-transferable, revocable license to access
          and use the Service as follows:
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            <strong>Hosted Service, paid plans:</strong> Commercial and business
            use is permitted, including use by and on behalf of your employer or
            organization;
          </li>
          <li>
            <strong>Hosted Service, free plans:</strong> Personal,
            non-commercial use only;
          </li>
          <li>
            <strong>Self-hosted deployments:</strong> Your use of the GAIA
            source code is governed solely by the PolyForm Noncommercial License
            1.0.0 accompanying that code, which permits noncommercial purposes
            only, including distributing the source code and making changes or
            new works based on it for those purposes, subject to the notice
            requirements of that license. This Agreement does not grant any
            additional rights in the source code, and the PolyForm license does
            not grant any right to use the hosted Service.
          </li>
        </ul>
      </div>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        8. User-Generated Content and License Grant
      </h2>
      <p className="mb-4">
        You retain all ownership rights in any content, data, or information you
        submit to the Service ("User Content"). By submitting User Content, you
        grant Company a worldwide, non-exclusive, royalty-free license to host,
        store, reproduce, process, transmit, display, and use the User Content
        to the extent necessary to operate, provide, and improve the Service,
        including passing it to the third-party providers described in our
        Privacy Policy. Company does not use content from your connected
        third-party integrations — including emails, calendar events, contacts,
        and other data retrieved from accounts you connect — to improve the
        Service, as described in the Privacy Policy. This license terminates
        when you delete the User Content or your account, except for reasonable
        backup copies retained for the period described in the Privacy Policy.
        Company will not sublicense or transfer this license to any third party
        except a service provider acting on Company's behalf, or an acquirer in
        connection with a merger or sale of assets. You represent and warrant
        that you have all necessary rights to grant this license and that your
        User Content does not infringe upon any third-party rights.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        9. AI Outputs and Assistant Actions
      </h2>
      <div className="mb-4">
        <h3 className="mt-4 mb-2 text-lg font-semibold">
          9.1 Accuracy of AI Outputs
        </h3>
        <p className="mb-4">
          The Service uses artificial intelligence to generate responses,
          summaries, and suggestions. AI outputs may be inaccurate, incomplete,
          outdated, or misleading, and may misinterpret your instructions or the
          contents of your connected accounts. You are responsible for reviewing
          and verifying AI outputs before relying on them. AI outputs do not
          constitute legal, medical, financial, tax, or other professional
          advice, and you should not rely on them as a substitute for a
          qualified professional.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          9.2 Authorization to Act on Your Behalf
        </h3>
        <p className="mb-2">
          GAIA is an agentic assistant. By connecting an integration and
          instructing the assistant, you authorize Company to take actions in
          that connected account on your behalf. Depending on the integrations
          you enable, this may include sending and modifying email, creating and
          deleting calendar events, posting messages, modifying records in
          connected tools, and running scheduled workflows that act when you are
          not present.
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            You are responsible for actions taken by the assistant under your
            account, including actions you approve and actions resulting from
            instructions, workflows, or automations you configure;
          </li>
          <li>
            Certain actions Company classifies as destructive require your
            explicit approval before they are carried out. This safeguard is
            provided on a best-efforts basis and is not guaranteed to catch
            every consequential action;
          </li>
          <li>
            You may disable any integration, revoke its access, or pause
            automations at any time from your account settings;
          </li>
          <li>
            You should not authorize the assistant to act on accounts containing
            information you cannot afford to have modified or deleted without
            independent backups.
          </li>
        </ul>
      </div>
    </>
  );
}

function TermsThirdPartyAndTermination() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        10. Third-Party Integrations
      </h2>
      <p className="mb-4">
        The Service connects to third-party products and services that Company
        does not own or control. Your use of any connected service is governed
        by that provider's own terms and privacy policy, and you are responsible
        for complying with them. Company does not warrant the availability,
        accuracy, or continued operation of any third-party service, and is not
        liable for any loss arising from a third-party service's downtime,
        errors, rate limits, changes to its API, suspension of your account with
        that provider, or discontinuation. A third-party provider may change or
        withdraw access at any time, which may remove functionality from the
        Service without notice.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        11. Privacy and Data Protection
      </h2>
      <p className="mb-4">
        Company's collection, use, and disclosure of personal information is
        governed by our Privacy Policy, which is incorporated herein by
        reference. Company hereby represents that it does not and will not sell,
        rent, or lease any personal data to third parties, and does not use
        content from your connected third-party integrations — including emails,
        calendar events, contacts, and other data retrieved from accounts you
        connect — to improve its services. Company may use content you submit
        directly to the Service to improve its services, as described in the
        Privacy Policy. Company processes personal data solely for the purposes
        of providing the Service and as otherwise described in the Privacy
        Policy.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        12. Modification and Discontinuation of the Service
      </h2>
      <p className="mb-4">
        Company may modify, suspend, or discontinue the Service, or any feature
        or integration within it, at any time. Where Company discontinues the
        Service in its entirety, or discontinues a paid feature in a way that
        materially reduces the value of your subscription, Company will provide
        at least thirty (30) days' notice by email or prominent notice in the
        Service and will refund the unused prepaid portion of your then-current
        billing period. Company is not otherwise liable to you or any third
        party for modifying, suspending, or discontinuing the Service.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">13. Termination</h2>
      <p className="mb-4">
        Either party may terminate this Agreement at any time with or without
        cause. Company may immediately terminate or suspend your access to the
        Service without prior notice if Company determines, in its sole
        discretion, that you have violated any provision of this Agreement. Upon
        termination, your right to use the Service shall immediately cease, and
        you shall discontinue all use of the Service. Sections 7, 8, 9, 13, 14,
        15, 16, 18, and 19 shall survive termination of this Agreement.
      </p>
    </>
  );
}

function TermsWarrantiesAndLiability() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        14. Disclaimers of Warranties
      </h2>
      <div className="mb-4">
        <p className="mb-2">
          THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS.
          COMPANY HEREBY DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING
          BUT NOT LIMITED TO:
        </p>
        <ul className="ml-6 list-disc">
          <li>
            IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
            PURPOSE, AND NON-INFRINGEMENT;
          </li>
          <li>
            WARRANTIES THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR
            SECURE;
          </li>
          <li>
            WARRANTIES REGARDING THE ACCURACY, RELIABILITY, OR COMPLETENESS OF
            ANY CONTENT, AI OUTPUT, OR ACTION TAKEN BY THE ASSISTANT.
          </li>
        </ul>
        <p className="mt-2">
          NO ADVICE OR INFORMATION, WHETHER ORAL OR WRITTEN, OBTAINED BY YOU
          FROM COMPANY OR THROUGH THE SERVICE SHALL CREATE ANY WARRANTY NOT
          EXPRESSLY STATED IN THIS AGREEMENT. SOME JURISDICTIONS DO NOT ALLOW
          THE EXCLUSION OF CERTAIN WARRANTIES, SO SOME OF THESE EXCLUSIONS MAY
          NOT APPLY TO YOU.
        </p>
      </div>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        15. Limitation of Liability
      </h2>
      <p className="mb-4">
        TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL
        COMPANY, ITS OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, OR AFFILIATES BE
        LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE
        DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF PROFITS, DATA, USE,
        GOODWILL, OR OTHER INTANGIBLE LOSSES, ARISING OUT OF OR RELATING TO YOUR
        USE OF THE SERVICE, REGARDLESS OF THE THEORY OF LIABILITY (CONTRACT,
        TORT, OR OTHERWISE) AND EVEN IF COMPANY HAS BEEN ADVISED OF THE
        POSSIBILITY OF SUCH DAMAGES. COMPANY'S TOTAL LIABILITY FOR ANY CLAIM
        ARISING OUT OF OR RELATING TO THIS AGREEMENT SHALL NOT EXCEED THE
        GREATER OF (A) THE AMOUNT YOU PAID TO COMPANY FOR THE SERVICE DURING THE
        TWELVE (12) MONTHS PRECEDING THE CLAIM AND (B) ONE HUNDRED UNITED STATES
        DOLLARS (USD $100). SOME JURISDICTIONS DO NOT ALLOW THE LIMITATION OR
        EXCLUSION OF LIABILITY FOR CERTAIN DAMAGES, SO SOME OF THESE LIMITATIONS
        MAY NOT APPLY TO YOU.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">16. Indemnification</h2>
      <p className="mb-4">
        You agree to defend, indemnify, and hold harmless Company and its
        officers, directors, employees, agents, and affiliates from and against
        any and all claims, damages, obligations, losses, liabilities, costs,
        and expenses (including reasonable attorneys' fees) arising from: (a)
        your use of the Service; (b) your violation of this Agreement; (c) your
        violation of any third-party rights; or (d) any content you submit to
        the Service.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        17. Modifications to Terms
      </h2>
      <p className="mb-4">
        Company reserves the right to modify this Agreement at any time by
        posting revised terms on the Service. Material changes will be
        communicated via email or prominent notice on the Service at least
        thirty (30) days before taking effect. Your continued use of the Service
        after the effective date of any modifications constitutes your
        acceptance of the revised Agreement. If you do not agree to the
        modifications, you must discontinue use of the Service.
      </p>
    </>
  );
}

function TermsDisputeResolution() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        18. Governing Law and Dispute Resolution
      </h2>
      <div className="mb-4">
        <h3 className="mt-4 mb-2 text-lg font-semibold">18.1 Governing Law</h3>
        <p className="mb-4">
          This Agreement is governed by the laws of the State of Delaware,
          United States, without regard to its conflict of law principles. This
          choice of law does not deprive you of the protection of any mandatory
          consumer law of the country or state in which you reside.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.2 Informal Resolution First
        </h3>
        <p className="mb-4">
          Before initiating arbitration, you and Company agree to try to resolve
          the dispute informally. Send a written notice describing the dispute
          and the relief sought to support@heygaia.so. If the dispute is not
          resolved within sixty (60) days, either party may begin arbitration.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.3 Binding Arbitration
        </h3>
        <p className="mb-4">
          Any dispute arising out of or relating to this Agreement or the
          Service that is not resolved informally shall be resolved by binding
          individual arbitration administered by the American Arbitration
          Association ("AAA") under its Consumer Arbitration Rules, as modified
          by this Agreement. The arbitration shall be seated in Wilmington,
          Delaware, and may be conducted by telephone, video conference, or on
          written submissions unless the arbitrator orders otherwise. If you are
          a consumer, you may elect to have the arbitration conducted in the
          county of your residence. Judgment on the award may be entered in any
          court of competent jurisdiction.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.4 Exceptions to Arbitration
        </h3>
        <p className="mb-2">Notwithstanding Section 18.3, either party may:</p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            Bring an individual action in small claims court, provided the
            dispute qualifies and remains in that court;
          </li>
          <li>
            Seek injunctive or other equitable relief in a court of competent
            jurisdiction to prevent actual or threatened infringement or misuse
            of intellectual property or unauthorized access to the Service.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.5 Thirty-Day Right to Opt Out
        </h3>
        <p className="mb-4">
          You may opt out of the arbitration agreement in Section 18.3 and the
          class action waiver in Section 18.6 by emailing support@heygaia.so
          with the subject line "Arbitration Opt-Out" within thirty (30) days of
          first accepting this Agreement, stating your name and the email
          address on your account. Opting out will not affect any other part of
          this Agreement, and Company will not terminate your account or
          otherwise penalize you for opting out.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.6 Class Action Waiver
        </h3>
        <p className="mb-4">
          YOU AND COMPANY AGREE THAT EACH MAY BRING CLAIMS AGAINST THE OTHER
          ONLY IN AN INDIVIDUAL CAPACITY, AND NOT AS A PLAINTIFF OR CLASS MEMBER
          IN ANY PURPORTED CLASS, COLLECTIVE, CONSOLIDATED, OR REPRESENTATIVE
          PROCEEDING. The arbitrator may not consolidate more than one person's
          claims and may not preside over any form of representative proceeding.
          If this Section 18.6 is found unenforceable as to a particular claim,
          that claim shall be severed from arbitration and brought in the courts
          located in Delaware, while all other claims remain in arbitration.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          18.7 Coordinated Claims
        </h3>
        <p className="mb-4">
          If twenty-five (25) or more claimants submit demands for arbitration
          raising substantially similar claims and represented by the same or
          coordinated counsel, the parties agree the demands shall be
          administered in sequential batches of no more than fifty (50) at a
          time, with each batch resolved before the next begins. All applicable
          limitation periods are tolled for claimants awaiting a later batch.
          This provision is intended to make resolution more efficient and does
          not limit any claimant's right to relief.
        </p>
      </div>
    </>
  );
}

function TermsClosing() {
  return (
    <>
      <h2 className="mt-6 mb-2 text-xl font-semibold">
        19. Severability and Waiver
      </h2>
      <p className="mb-4">
        If any provision of this Agreement is held to be invalid or
        unenforceable, the remaining provisions shall remain in full force and
        effect. The failure of Company to enforce any provision of this
        Agreement shall not constitute a waiver of such provision or any other
        provision.
      </p>

      <h2 className="mt-6 mb-2 text-xl font-semibold">
        20. Contact Information
      </h2>
      <p>
        For any questions, concerns, or notices regarding this Agreement, please
        contact us at:
        <br />
        The Experience Company, Inc.
        <br />
        Email:{" "}
        <a className="text-blue-500 underline" href="mailto:support@heygaia.so">
          support@heygaia.so
        </a>
      </p>
    </>
  );
}

const TermsOfService = () => {
  const termsSchema = generateWebPageSchema(
    "Terms of Service",
    "Review GAIA's Terms of Service to understand your rights, responsibilities, and the terms governing your use of our AI assistant platform.",
    `${siteConfig.url}/terms`,
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
      <div className="flex w-full flex-col items-center justify-center">
        <div className="privacy-policy w-full max-w-(--breakpoint-xl) px-4 pb-6 pt-24 sm:px-6 lg:px-8">
          <TermsIntro />
          <TermsAccounts />
          <TermsPayments />
          <TermsServiceAndContent />
          <TermsThirdPartyAndTermination />
          <TermsWarrantiesAndLiability />
          <TermsDisputeResolution />
          <TermsClosing />
        </div>
      </div>
    </>
  );
};

export default TermsOfService;
