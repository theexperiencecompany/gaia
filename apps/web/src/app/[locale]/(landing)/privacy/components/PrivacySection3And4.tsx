import { Link } from "@heroui/link";

export function PrivacySection3And4() {
  return (
    <>
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
          3.1 AI Model Providers
        </h3>
        <p className="mb-4">
          To generate responses, we share content you submit with third-party AI
          model providers who process it on our behalf. This may include the
          contents of messages, files, and data retrieved from accounts you have
          connected. We do not use content from your connected third-party
          integrations to improve our services, as described in Section 2.3.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          3.2 Service Providers
        </h3>
        <p className="mb-2">
          We may share your information with trusted third-party service
          providers who assist us in operating our business, including:
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>Cloud hosting and infrastructure providers;</li>
          <li>Payment processing companies;</li>
          <li>
            Integration platforms that connect the Service to your third-party
            accounts;
          </li>
          <li>Customer support and communication platforms;</li>
          <li>Analytics and monitoring services;</li>
          <li>Security and fraud prevention services.</li>
        </ul>
        <p className="mb-2">
          <strong>Google User Data:</strong> We only share Google user data with
          service providers who are necessary for providing our AI assistant
          functionality and who have agreed to appropriate data protection
          measures. We do not transfer Google user data to third parties for
          advertising or other unrelated purposes.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          3.3 Legal Requirements
        </h3>
        <p className="mb-2">
          We may disclose your information when required by law or when we
          believe in good faith that disclosure is necessary to:
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            Comply with a legal obligation, court order, or government request;
          </li>
          <li>Protect and defend our rights or property;</li>
          <li>
            Prevent or investigate possible wrongdoing in connection with the
            Service;
          </li>
          <li>
            Protect the personal safety of users of the Service or the public.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          3.4 Business Transfers
        </h3>
        <p className="mb-4">
          In the event of a merger, acquisition, or sale of all or a portion of
          our assets, your information may be transferred to the acquiring
          entity, subject to the same privacy protections outlined in this
          Policy.
        </p>
      </div>

      <h2 className="mt-4 mb-2 text-xl font-semibold">
        4. Google User Data and Limited Use
      </h2>
      <div className="mb-4">
        <p className="mb-4">
          GAIA's use and transfer of information received from Google APIs to
          any other app will adhere to the{" "}
          <Link
            className="text-blue-500 underline"
            href="https://developers.google.com/terms/api-services-user-data-policy"
            isExternal
            showAnchorIcon={false}
          >
            Google API Services User Data Policy
          </Link>
          , including the Limited Use requirements.
        </p>
        <p className="mb-2">In particular:</p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            We use Google user data only to provide or improve user-facing
            features that are prominent in the Service;
          </li>
          <li>
            We do not use Google user data to develop or improve generalized
            artificial intelligence or machine learning models;
          </li>
          <li>
            We do not transfer or sell Google user data for advertising,
            marketing, or any other unrelated purpose;
          </li>
          <li>
            We do not allow humans to read Google user data unless we have your
            affirmative consent for specific messages, it is necessary for
            security purposes or to comply with applicable law, or the data has
            been aggregated and anonymized for internal operations;
          </li>
          <li>
            You may disconnect any Google integration at any time from your
            account settings, and you may revoke our access directly through
            your{" "}
            <Link
              className="text-blue-500 underline"
              href="https://myaccount.google.com/permissions"
              isExternal
              showAnchorIcon={false}
            >
              Google Account permissions page
            </Link>
            .
          </li>
        </ul>
      </div>
    </>
  );
}
