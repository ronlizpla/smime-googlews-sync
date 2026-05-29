# S/MIME Google Workspace Automation Script

A production-grade Python tool designed to automate loading and assigning S/MIME IV (Individual Validated) certificates from a local directory directly into user accounts across any Google Workspace tenant.

---

## Architecture Overview

The tool operates by decrypting S/MIME PKCS#12 (`.p12` or `.pfx`) files, parsing the certificates to extract the owner's email address from the Subject Alternative Name (SAN) or Common Name (CN), and then programmatically uploading them to the corresponding Google Workspace accounts via the Gmail API. 

It accomplishes tenant-wide administration without user interaction by using a **Google Cloud Service Account with Domain-Wide Delegation (DWD)**.

```
┌─────────────────┐      1. Scan Directory      ┌─────────────────┐
│  Local Folder   │ ──────────────────────────> │  sync_smime.py  │
│  (.p12 / .pfx)  │                             └────────┬────────┘
└─────────────────┘                                      │
                                                         │ 2. Extract Email &
                                                         │    Decrypt Cert
                                                         ▼
┌─────────────────┐      3. Impersonate User    ┌─────────────────┐
│ Google Gmail API│ <────────────────────────── │ Service Account │
└─────────────────┘       via DWD Credentials   └─────────────────┘
```

---

## 1. Prerequisites & Google Workspace Setup

To execute this script, you must configure the destination Google Workspace tenant.

### Step A: Enable Hosted S/MIME in Gmail
1. Log in to the [Google Admin Console](https://admin.google.com) as a Super Admin.
2. Go to **Apps** > **Google Workspace** > **Gmail** > **User settings**.
3. Scroll to **S/MIME** and check the box **"Enable S/MIME encryption for sending and receiving emails"**.
4. Save the changes.

### Step B: Create a Google Cloud Project & Service Account
1. Open the [Google Cloud Console](https://console.cloud.google.com).
2. Create a new project or select an existing one.
3. Enable the **Gmail API**:
   - Go to **APIs & Services** > **Library**.
   - Search for **Gmail API** and click **Enable**.
4. Create the Service Account:
   - Go to **IAM & Admin** > **Service Accounts**.
   - Click **Create Service Account**. Give it a descriptive name (e.g. `smime-sync-bot`).
   - Click **Done** (do not assign roles in GCP).
5. Generate the Service Account JSON Credentials Key:
   - Select the newly created service account.
   - Go to the **Keys** tab.
   - Click **Add Key** > **Create new key**. Select **JSON** and download the file. Keep this file secure!

### Step C: Configure Domain-Wide Delegation (DWD)
1. In the Google Admin Console, go to **Security** > **Access and data control** > **API controls**.
2. Click **Manage Domain Wide Delegation**.
3. Click **Add new**.
4. Enter the **Client ID** of the Service Account (found in the JSON credentials file as `client_id`).
5. Enter the following **OAuth Scopes** separated by a comma:
   - `https://www.googleapis.com/auth/gmail.settings.basic`
   - `https://www.googleapis.com/auth/gmail.settings.sharing`
6. Click **Authorize**.

---

## 2. Installation

1. Make sure Python 3.8+ is installed on your machine.
2. Clone or place this repository locally.
3. Install the dependencies using pip:
   ```powershell
   pip install -r requirements.txt
   ```

---

## 3. Usage & Command-Line Arguments

The script is invoked via command line. It supports dry-run validation, verbose logging, and automatically configuring uploaded certificates as default.

```powershell
python sync_smime.py --credentials <path-to-json> --directory <path-to-certs> [options]
```

### Options
| Parameter | Short | Description |
| :--- | :--- | :--- |
| `--credentials` | `-c` | **Required.** Path to the Google Cloud Service Account JSON credentials file. |
| `--directory` | `-d` | **Required.** Path to the directory containing `.p12` or `.pfx` certificate files. |
| `--password` | `-p` | Password to decrypt the PKCS#12 files. (Can also be set as an environment variable `SMIME_PASSWORD`). |
| `--default` | | Set the uploaded certificate as the default S/MIME key for the user's email address. |
| `--dry-run` | | Perform local validations and parse certificate emails without making API requests to Google. |
| `--verbose` | `-v` | Enable debug logs for verbose troubleshooting output. |

### Environment Variable for Passwords
Instead of exposing the password in the console command history, you can set it as an environment variable:
```powershell
$env:SMIME_PASSWORD="your-p12-password"
python sync_smime.py -c credentials.json -d C:\path\to\certs --default
```

---

## 4. Desktop GUI Interface

You can also run the utility using a modern, interactive desktop interface.

### Running the GUI
To launch the GUI:
```powershell
python gui_sync.py
```

### Features:
- **Interactive Browsing:** Select your Service Account JSON file and Certificates folder using file/folder picker dialogs.
- **Log Monitor Window:** Output and API logs are displayed in real-time within the console output pane.
- **Thread-safe Execution:** Sync operations run in a background thread to prevent UI freezing.
- **Visual Completion Dialog:** Shows a summary popup when the sync finishes.

---

## 5. Run Example (Step-by-Step)

### Step 1: Run in Dry-Run Mode (Safe Verification)
Run the script with the `--dry-run` flag to scan your certificates, verify passwords, and extract email addresses without touching Google API:
```powershell
python sync_smime.py -c credentials.json -d C:\Users\Example\Certs -p "mySecretPassword" --dry-run
```
Expected output:
```text
2026-05-29 14:00:00 [INFO] ==================================================
2026-05-29 14:00:00 [INFO] Starting S/MIME Google Workspace Sync Script
2026-05-29 14:00:00 [INFO] Directory: C:\Users\Example\Certs
2026-05-29 14:00:00 [INFO] MODE: DRY-RUN (Local validations only)
2026-05-29 14:00:00 [INFO] ==================================================
2026-05-29 14:00:00 [INFO] Found 2 certificate file(s).
2026-05-29 14:00:00 [INFO] Processing certificate: user1_cert.p12
2026-05-29 14:00:00 [INFO]   Extracted owner email: user1@yourdomain.com
2026-05-29 14:00:00 [INFO]   Cert Subject: CN=John Doe,O=Company,C=US
2026-05-29 14:00:00 [INFO]   Valid From:   2026-05-20 00:00:00+00:00
2026-05-29 14:00:00 [INFO]   Valid Until:  2027-05-20 23:59:59+00:00
2026-05-29 14:00:00 [INFO]   [DRY-RUN] Would upload certificate for user: user1@yourdomain.com
...
2026-05-29 14:00:00 [INFO] ==================================================
2026-05-29 14:00:00 [INFO] Sync Execution Report:
2026-05-29 14:00:00 [INFO]   Total Processed: 2
2026-05-29 14:00:00 [INFO]   Successful:      2
2026-05-29 14:00:00 [INFO]   Failed:          0
2026-05-29 14:00:00 [INFO] ==================================================
```

### Step 2: Run Live Upload
To upload the certificates and configure them as default:
```powershell
python sync_smime.py -c credentials.json -d C:\Users\Example\Certs -p "mySecretPassword" --default
```

---

## Troubleshooting

- **Error: 403 Access Denied (impersonation failed)**
  Ensure the Service Account Client ID is authorized in **Domain-Wide Delegation** in the Google Admin Console and that the scopes are typed correctly. Make sure you wait up to 15-20 minutes, as Google API delegation access changes can take time to propagate.
- **Error: Certificate Email Mismatch**
  If the target email doesn't match the primary address or a valid Send As alias of the impersonated user, the upload will fail. Add the email as an alias inside the user's Gmail/Admin Console settings.
- **Error: Hosted S/MIME not enabled**
  Ensure S/MIME is enabled in the Gmail settings of the Google Admin Console.
