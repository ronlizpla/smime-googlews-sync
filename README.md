# S/MIME Google Workspace Automation Script

A production-grade Python tool designed to automate loading and assigning S/MIME IV (Individual Validated) certificates from a local directory directly into user accounts across any Google Workspace tenant.

---

## 1. Important S/MIME Certificate Requirements
Google Workspace enforces strict validation policies for custom S/MIME Root Certificates:
*   **Three-Tier Chain Mandatory**: The certificate chain **must include at least one intermediate certificate**. Google Workspace will reject and distrust leaf (user) certificates signed directly by a Root CA.
*   **Chain Bundling**: The final PKCS#12 (`.p12` or `.pfx`) file uploaded for each user must contain their private key, user certificate, and the intermediate certificate chain.

This tool consumes provider-issued PKCS#12 (`.p12`/`.pfx`) files; the PFX must bundle the user key, user certificate, and intermediate chain as described above.

---

## 2. Prerequisites & Google Workspace Setup

### Step A: Enable Hosted S/MIME in Gmail
1. Log in to the [Google Admin Console](https://admin.google.com) as a Super Admin.
2. Go to **Apps** > **Google Workspace** > **Gmail** > **User settings**.
3. Scroll to **S/MIME** and check the box **"Enable S/MIME encryption for sending and receiving emails"**.
4. Upload your CA root certificate under the **"Accept these additional Root Certificates for specific domains"** section, and map it to your target domain (e.g., `yourdomain.com`). (Not required when using certs issued by a publicly trusted CA.)

### Step B: Create a Google Cloud Project & Service Account
1. Open the [Google Cloud Console](https://console.cloud.google.com).
2. Enable the **Gmail API** in your project.
3. Create a Service Account (e.g., `smime-sync-bot`) and download a **JSON credentials key**. Keep this file secure!
4. Alternatively, use the automated setup script (or the **"Setup GCP Project & Permissions"** button in the GUI):
   ```powershell
   # Use an existing project:
   .\setup_gcp.ps1 -ProjectId "your-unique-project-id"

   # Or create a brand-new project as part of setup:
   .\setup_gcp.ps1 -ProjectId "your-unique-project-id" -CreateProject
   ```
   The script enables the Gmail API, creates the service account, generates the key, and prints the exact Client ID + scopes you need for Domain-Wide Delegation. Parameters: `-ProjectId` (required), `-ServiceAccountName`, `-KeyOutputPath`, `-CreateProject`.

### Step C: Configure Domain-Wide Delegation (DWD)
1. In the Google Admin Console, go to **Security** > **Access and data control** > **API controls**.
2. Click **Manage Domain Wide Delegation** > **Add new**.
3. Enter the **Client ID** of the Service Account (found in the JSON credentials file as `client_id`).
4. Enter the following **OAuth Scopes** separated by a comma:
   - `https://www.googleapis.com/auth/gmail.settings.basic`
   - `https://www.googleapis.com/auth/gmail.settings.sharing`
5. Click **Authorize**.

---

## 3. Installation

1. Make sure Python 3.8+ is installed on your machine.
2. Install the hardened dependencies using pip:
   ```powershell
   pip install -r requirements.txt
   ```

---

## 4. Usage & Command-Line Arguments

The script is invoked via command line. It supports dry-run validation, verbose logging, and automatically configuring uploaded certificates as default.

```powershell
python sync_smime.py --credentials <path-to-json> --directory <path-to-certs> [options]
```

### Options
| Parameter | Short | Description |
| :--- | :--- | :--- |
| `--credentials` | `-c` | **Required.** Path to the Google Cloud Service Account JSON credentials file. |
| `--directory` | `-d` | **Required.** Path to the directory containing `.p12` or `.pfx` certificate files. |
| `--password` | `-p` | Global password to decrypt the PKCS#12 files. (Can also be set as an environment variable `SMIME_PASSWORD`). |
| `--password-csv` | | Explicit path to a per-certificate password CSV. Overrides the auto-discovered `passwords.csv` in the certificate directory (see below). |
| `--default` | | Set the uploaded certificate as the default S/MIME key for the user's email address. |
| `--dry-run` | | Perform local validations and parse certificate emails without making API requests to Google. |
| `--verbose` | `-v` | Enable debug logs for verbose troubleshooting output. |

### ⚠️ Security warning: Shell History Exposure
Avoid passing sensitive passwords directly on the command line using `-p` or `--password`. Instead, set the password as an environment variable to prevent it from being stored in your shell history:

```powershell
$env:SMIME_PASSWORD="your-secure-p12-password"
python sync_smime.py -c credentials.json -d C:\path\to\certs --default
```

### Per-certificate passwords (`passwords.csv`)
When each PFX has a different password, provide a CSV mapping certificates to passwords. There are two ways to supply it:

- **Auto-discovered:** drop a `passwords.csv` **in the same folder as the certificates** (used automatically by both CLI and GUI — no flags).
- **Explicit override:** pass `--password-csv C:\path\to\passwords.csv` (CLI) or use the **"Per-Certificate Password CSV"** picker (GUI). This takes precedence over an auto-discovered `passwords.csv`.

The CSV needs a `password` column plus at least one identifier column — `file` (certificate filename) and/or `email` (the address inside the cert; matches a file literally named after that email, e.g. `user@example.com.pfx`). Headers are case-insensitive.

```csv
file,email,password
alice.pfx,alice@example.com,Pa$$w0rd-alice
bob.pfx,bob@example.com,S3cret!-bob
```

- Any certificate **not** listed falls back to the global password (`--password` / `SMIME_PASSWORD`).
- A `passwords.csv` in the certs folder is excluded from git; delete it after the import, as it holds plaintext passwords.

---

## 5. Desktop GUI Interface

You can also run the utility using a modern, interactive desktop interface.

### Running the GUI
*   **Option A**: Run using the standalone pre-compiled executable (contains all dependencies):
    ```powershell
    # Double-click the file to open:
    .\dist\gui_sync.exe
    ```
*   **Option B**: Launch from the Python virtual environment:
    ```powershell
    .\venv\Scripts\python gui_sync.py
    ```
*   **Option C**: Run the quick helper script:
    ```powershell
    .\run_gui.bat
    ```

### Features:
- **Interactive Browsing:** Select your Service Account JSON file and Certificates folder using file/folder picker dialogs.
- **Per-Certificate Password CSV:** Optionally select a CSV that overrides the auto-discovered `passwords.csv` (same format as the CLI section above).
- **One-Click GCP Setup:** The **"Setup GCP Project & Permissions"** button provisions the Google Cloud service account and key. It prompts for Project ID, service account name, output key file, and whether to create a new project, then runs `setup_gcp.ps1` and streams its output into the log console. On success it auto-fills the credentials path and reminds you of the one-time Domain-Wide Delegation step. (Requires the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and `gcloud auth login` completed.)
- **Log Monitor Window:** Output and API logs are displayed in real-time within the console output pane.
- **Thread-safe Execution:** Sync operations run in a background thread to prevent UI freezing.
- **Safe Defaults:** Safe validation safeguards (e.g. `dry-run` defaults to `True`, and `set_default` defaults to `False` to prevent unintentional default updates).
