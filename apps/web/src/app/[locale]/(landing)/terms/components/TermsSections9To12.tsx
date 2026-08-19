export function TermsSections9To12() {
  return (
    <>
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
    </>
  );
}
