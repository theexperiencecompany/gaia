export function PrivacySection1() {
  return (
    <>
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
            <strong>Account Information:</strong> Name, email address, username,
            password, and other registration information you provide when
            creating an account;
          </li>
          <li>
            <strong>Payment Information:</strong> Credit card numbers, billing
            addresses, and other payment-related information processed through
            our third-party payment processors;
          </li>
          <li>
            <strong>Profile Information:</strong> Optional profile information,
            preferences, and settings you choose to provide;
          </li>
          <li>
            <strong>Communication Data:</strong> Information you provide when
            you contact us for support, feedback, or other communications;
          </li>
          <li>
            <strong>User Content:</strong> All text, files, images, audio, and
            other content you submit to or through the Service.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          1.2 Information We Collect Automatically
        </h3>
        <p className="mb-2">
          The information described in this section is linked to your account
          and is not anonymous.
        </p>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            <strong>Device Information:</strong> IP address, device type,
            operating system, browser type and version, device identifiers, and
            mobile network information;
          </li>
          <li>
            <strong>Usage Data:</strong> Information about how you use the
            Service, including features accessed, time spent, interaction
            patterns, and performance metrics. This data is associated with your
            account identifier;
          </li>
          <li>
            <strong>Location Data:</strong> General location information derived
            from your IP address (not precise geolocation unless explicitly
            consented);
          </li>
          <li>
            <strong>Cookies and Tracking Technologies:</strong> Information
            collected through cookies, web beacons, pixels, and similar tracking
            technologies.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          1.3 Information from Third Parties
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            <strong>Authentication Services:</strong> If you use third-party
            authentication services (e.g., Google, GitHub), we may receive basic
            profile information such as your name, email address, and profile
            picture;
          </li>
          <li>
            <strong>Google User Data:</strong> When you connect Google services,
            we may access and collect data from your Google account including
            but not limited to email, calendar events, contacts, and documents
            as authorized by you through Google's OAuth consent process;
          </li>
          <li>
            <strong>Connected Integrations:</strong> When you connect a
            third-party account (such as Slack, Notion, or GitHub), we receive
            data from that account as authorized by you during the connection
            process;
          </li>
          <li>
            <strong>Analytics Providers:</strong> Information from third-party
            analytics services that help us understand Service usage and
            performance;
          </li>
          <li>
            <strong>Security Services:</strong> Information from fraud
            prevention and security services to protect against unauthorized
            access.
          </li>
        </ul>
      </div>
    </>
  );
}
