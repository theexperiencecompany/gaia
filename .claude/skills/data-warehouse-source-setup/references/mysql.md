> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Linking MySQL as a source - Docs

Copy page

# Linking MySQL as a source - Docs

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_9608fcca70)

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_dark_a92b0e022d)

Let AI connect your sources for you

Skip the manual setup — run this in your project and the wizard auto-detects your databases and APIs and connects them to PostHog.

`npx @posthog/wizard warehouse`

[Learn more](/wizard.md)

![PostHog Wizard hedgehog](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)

![](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)Let AI connect your sources for you

The MySQL connector can link your database tables to PostHog.

To link MySQL:

1.  Go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and the sources tab in PostHog
2.  Click **New source** and select MySQL
3.  Enter your database connection details:
    -   **Host:** The hostname or IP your database server like `db.example.com` or `123.132.1.100`.
    -   **Port:** The port your database server is listening to. The default is `3306`.
    -   **Database:** The name of the database you want like `analytics_db`.
    -   **User:** The username with the necessary permissions to access the database.
    -   **Password:** The password for the user.
    -   **Schema:** The schema for your database where your tables are located. The default is `public`.
    -   **Use SSL:** Whether to use SSL for the connection. Default is enabled.
4.  If you need to connect through an SSH tunnel, enable and configure it (optional):
    -   **Tunnel host:** The hostname of your SSH server.
    -   **Tunnel port:** The port your SSH server is listening on.
    -   **Authentication type:**
        -   For password authentication, enter your SSH username and password.
        -   For key-based authentication, enter your SSH username, private key, and optional passphrase.
5.  Click **Next**

The data warehouse then starts syncing your MySQL data. You can see details and progress in the [sources tab](https://app.posthog.com/data-management/sources).

## Configuration

| Option | Description |
| --- | --- |
| HostType: textRequired: True | Must be reachable from the public internet. Add PostHog's egress IP addresses to your firewall allowlist (see the docs above) and use a public host. localhost and private IPs (10.x, 172.16-31.x, 192.168.x) can't be reached. For a database that can't be exposed publicly, enable the SSH tunnel below. |
| PortType: numberRequired: True |
| DatabaseType: textRequired: True |
| UserType: textRequired: True |
| PasswordType: passwordRequired: True |
| SchemaType: textRequired: False |
| Use SSL?Type: selectRequired: True |
| Use SSH tunnel?Type: ssh-tunnelRequired: False |

## Selecting columns

By default, PostHog syncs all columns from each table. To sync only specific columns:

1.  During source setup, click **Columns** next to any table in the table picker.
2.  Uncheck columns you don't want to sync.
3.  Primary key columns and the incremental sync field (if configured) are always synced and cannot be disabled.

You can also change column selection after setup:

1.  Go to the [sources tab](https://app.posthog.com/data-management/sources) and click your MySQL source.
2.  Click **Configure** next to any schema.
3.  Under **Columns**, select which columns to sync.

**Adding columns to existing syncs**

When you add columns to a schema using incremental or append sync, PostHog prompts you to choose:

-   **Sync forward only** - New columns are populated only for future data. Existing rows show `NULL` for the new columns.
-   **Full resync** - Triggers a complete resync to backfill the new columns for all rows.

**Decimal precision limits**

Numeric or decimal columns with values exceeding a precision of 76 or scale of 32 cannot be synced. If your sync fails with this error, you have three options:

-   Constrain the column with a lower precision/scale
-   Cast it to text in a view
-   Round the values at the source

#### Inbound IP addresses

We use a set of IP addresses to access your instance. To ensure this connector works, add these IPs to your inbound security rules:

| US | EU |
| --- | --- |
| 44.205.89.55 | 3.75.65.221 |
| 52.4.194.122 | 18.197.246.42 |
| 44.208.188.173 | 3.120.223.253 |

### Was this page useful?

HelpfulCould be better