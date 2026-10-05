### Documentation
This documentation is an svg image to be able to embed rich HTML and use colors. If you need to select text, open the image in a new window.

![](./documentation.svg)

## Installation
Install all required dependencies using `pip`:
```bash
pip install -r requirements.txt
```

## Google Calendar Sync Setup
To sync your generated schedule directly to Google Calendar, you need to set up a Google Cloud Service Account. This allows the script to update your calendar in the background without needing a web browser login.

### 1. Enable the Google Calendar API
1. Go to the [Google Cloud Console](https://console.cloud.google.com) and ensure your project is selected.
2. In the left sidebar, navigate to **APIs & Services** > **Library**.
3. Search for "Google Calendar API", click on it, and click **Enable**.

### 2. Create the Service Account
**Note**: You do not need to configure an OAuth consent screen (User Data vs Application Data) because we are using a Service Account, which operates silently in the background.
1. In the left sidebar, navigate to **IAM & Admin** > **Service Accounts** (do *not* go to "Credentials" > "OAuth client ID").
2. Click **+ CREATE SERVICE ACCOUNT** at the top.
3. Give it a name (e.g., "ra-scheduler-sync") and click **Create and Continue**.
4. Skip the "Grant this service account access to project" step (no project roles are needed). Just click **Done**.

### 3. Generate the JSON Key File
1. Click on the email address of your newly created Service Account in the list.
2. Go to the **Keys** tab.
3. Click **Add Key** > **Create new key**.
4. Select **JSON** as the key type and click **Create**.
5. The `.json` key file will be downloaded. Place it in the same directory as this script and name it `service_account.json`. **Keep this file secure and do not commit it to version control.**

### 4. Create and Share a Target Calendar
It is highly recommended to create a dedicated, empty calendar for this schedule, rather than mixing it with your personal events.
1. Copy the email address of your new Service Account (e.g., `ra-scheduler-sync@your-project.iam.gserviceaccount.com`).
2. Open [Google Calendar](https://calendar.google.com) in your web browser.
3. Click the `+` next to **Other calendars** on the left sidebar and select **Create new calendar**.
4. Name it (e.g., "RA Work Schedule") and click **Create calendar**.
5. Go back to the main screen, hover over your new calendar under "My calendars", click the three vertical dots (⋮), and select **Settings and sharing**.
6. Scroll down to the **Share with specific people or groups** section and click **Add people and groups**.
7. Paste the Service Account's email address.
8. Change the permission to **"Make changes to events"**.
9. Click **Send**.

When you run the script, it will ask you if you want to sync, and it will let you select this calendar from a list.
