export function PrivacySection2() {
  return (
    <>
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
            Providing, maintaining, and improving the Service and its features;
          </li>
          <li>
            Processing and responding to your requests and interactions with the
            AI assistant;
          </li>
          <li>
            <strong>Google User Data Processing:</strong> Using Google user data
            solely to provide and improve our AI assistant functionality,
            including processing emails, calendar events, and documents to
            provide relevant assistance and responses;
          </li>
          <li>
            Personalizing your experience and delivering relevant content and
            recommendations;
          </li>
          <li>
            Processing payments and managing your account and subscriptions.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          2.2 Communication and Support
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>Responding to your inquiries, comments, and support requests;</li>
          <li>
            Sending you service-related communications, updates, and
            notifications;
          </li>
          <li>Providing customer support and technical assistance;</li>
          <li>
            Conducting surveys and gathering feedback to improve our services.
          </li>
        </ul>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          2.3 Analytics and Improvement
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            Analyzing usage patterns to understand how the Service is used and
            to improve functionality;
          </li>
          <li>
            Monitoring and analyzing trends, usage, and activities in connection
            with the Service;
          </li>
          <li>Developing new features, services, and products.</li>
        </ul>
        <p className="mb-4">
          <strong>
            We may use content you submit to the Service to improve our services
            and products.
          </strong>{" "}
          We do not use content from your connected third-party integrations —
          including emails, calendar events, contacts, and other data retrieved
          from accounts you connect — to improve our services. Content from
          connected accounts is used solely to operate the Service at your
          direction.
        </p>

        <h3 className="mt-4 mb-2 text-lg font-semibold">
          2.4 Security and Legal Compliance
        </h3>
        <ul className="mb-4 ml-6 list-disc">
          <li>
            Protecting against fraud, unauthorized access, and other security
            threats;
          </li>
          <li>
            Investigating and preventing violations of our Terms of Service;
          </li>
          <li>
            Complying with applicable laws, regulations, and legal obligations;
          </li>
          <li>
            Enforcing our rights and protecting our property and interests.
          </li>
        </ul>
      </div>
    </>
  );
}
