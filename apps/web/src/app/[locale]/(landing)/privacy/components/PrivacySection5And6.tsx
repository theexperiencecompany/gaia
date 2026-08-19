export function PrivacySection5And6() {
  return (
    <>
      <h2 className="mt-4 mb-2 text-xl font-semibold">
        5. How the Assistant Acts on Your Behalf
      </h2>
      <div className="mb-4">
        <h3 className="mt-4 mb-2 text-lg font-semibold">
          5.1 Autonomous Actions
        </h3>
        <p className="mb-2">
          GAIA is an agentic assistant. When you connect an integration, the
          assistant can read from and write to that account on your behalf.
          Depending on the integrations you enable and the instructions you
          give, this may include:
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>Reading, drafting, sending, labelling, and archiving email;</li>
          <li>Creating, modifying, and deleting calendar events;</li>
          <li>
            Posting messages and reading conversations in connected chat
            platforms;
          </li>
          <li>
            Creating, updating, and deleting records in other connected tools;
          </li>
          <li>
            Running scheduled workflows and background tasks that act without
            you being present.
          </li>
        </ul>
        <p className="mb-4">
          Certain actions we classify as destructive require your explicit
          approval before they are carried out. You can review connected
          integrations, disable them, and revoke their access at any time from
          your account settings.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          5.2 Automated Decision-Making
        </h3>
        <p className="mb-4">
          The Service uses automated processing to decide which content is
          relevant to you, which notifications to send, and which actions to
          take or suggest in response to your instructions. We do not use
          automated decision-making to produce legal effects concerning you or
          effects of similarly significant impact, such as decisions about
          credit, employment, insurance, or access to essential services. You
          may contact us at any time to request human review of an automated
          action taken by the Service.
        </p>
      </div>

      <h2 className="mt-4 mb-2 text-xl font-semibold">
        6. Cookies and Tracking Technologies
      </h2>
      <div className="mb-4">
        <p className="mb-2">
          We use cookies and similar tracking technologies to collect
          information about your use of the Service. These technologies include:
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          6.1 Types of Cookies
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            <strong>Essential Cookies:</strong> Required for basic Service
            functionality and cannot be disabled;
          </li>
          <li>
            <strong>Analytics Cookies:</strong> Help us understand how you use
            the Service and improve its performance;
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
          6.2 Cookie Management
        </h3>
        <p className="mb-4">
          You can control cookies through your browser settings. However,
          disabling certain cookies may limit your ability to use some features
          of the Service. For more information about managing cookies, please
          refer to your browser's help documentation.
        </p>
      </div>
    </>
  );
}
