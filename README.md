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

When you run the script, it will automatically load your settings, check your Google Calendar in the background, and display an uncluttered overview dashboard.

## Running the Scheduler

Run the scheduler with:
```bash
python3 src/ra-master-scheduler.py
```

### Features & CLI Interface

- **Initial Setup vs. Instant Launch**:
  - **First Run**: If no settings are configured yet, an interactive wizard prompts for your start year/month, duration, target workdays (Master's: 10, PhD: 12), and overtime preference.
  - **Subsequent Runs**: Automatically loads your settings and saved constraints, checks Google Calendar in the background, renders the overview dashboard, and presents an interactive menu.

- **Responsive Horizontal Month Stacking**:
  - Months are automatically stacked side-by-side to fit your terminal width.
  - Wraps to a new row only when an entire month cannot fit on the current row.
  - Each month displays a compact progress line indicating worked days against monthly targets (e.g. `10/10d (77.5h)`).

- **Interactive Calendar Day Editor (`[1]` in menu)**:
  - Full-screen terminal UI (TUI) powered by `curses`.
  - Use **Arrow Keys** (←, →, ↑, ↓) to navigate across days and weeks, or **PgUp / PgDn** (`[` / `]`) to jump month-by-month.
  - **Shortcut Keys**:
    - `[F]`: Toggle Forced Workday
    - `[P]`: Toggle Paid Leave (Paid Disabled Day)
    - `[U]`: Toggle Unpaid Leave (Unpaid Disabled Day)
    - `[C]` / `[Delete]`: Clear constraint (revert to automatic)
    - `[S]`: Solve schedule in memory immediately (without saving to disk)
    - `[Q]` / `[Esc]`: Exit editor (prompts to save changes if modified)

- **Lock Past Workdays (`[2]` in menu)**:
  - Detects all previously planned workdays before today that have already passed.
  - Converts them into forced workdays with one click so future optimization will never alter passed work history.

- **Background Google Calendar Sync & Visual Comparison (`[3]` in menu)**:
  - Non-intrusively checks remote Google Calendar events on startup.
  - If external additions or changes are found, provides a formatted list of changes to review.
  - Shows side-by-side **Before & After visual calendar comparison** for only the months affected by the changes, solving the schedule in advance and warning if the changes cause infeasibility.
  - Push current schedules and export to public iCal URLs with ease.

- **Detailed Day-by-Day Table (`[6]` in menu)**:
  - View full day-by-day tables with 7-day rolling window hour sums on demand without cluttering the main dashboard.

- **Standard Timing & Alerts (iCal & Google Calendar)**:
  - Workdays and leave days are scheduled during normal working hours: **09:00 – 17:45** (`Asia/Tokyo`).
  - Automatically configured with a popup/display alert **10 hours before starting** (at 23:00 the evening before).

- **Paid Leave Accounting**:
  - Paid leave days count towards your monthly total days worked target (e.g. 9 physical workdays + 1 paid leave = 10 target days).
  - Each paid leave day accounts for **7.75 hours of work** in the schedule, monthly progress, rolling 7-day limits, and calendar exports.
