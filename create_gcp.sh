#!/usr/bin/env bash
#
# create_gcp.sh — macOS/Linux port of create_gcp.ps1
#
# Creates a GCP project (optional), enables the Gmail API, creates a service
# account, and generates a JSON key for the S/MIME Workspace Sync tool.
#
# Requires: gcloud CLI (https://cloud.google.com/sdk/docs/install), authenticated
#           via `gcloud auth login`. Also reads client_id from the key via python3.
#
# Usage:
#   ./create_gcp.sh --project-id my-smime-sync-prod
#   ./create_gcp.sh --project-id existing-proj --skip-project-create   # SA+key only
#   ./create_gcp.sh --project-id p --sa-name smime-sync-bot --key-out ./credentials.json
#
set -euo pipefail

PROJECT_ID=""
SA_NAME="smime-sync-bot"
KEY_OUT="./credentials.json"
SKIP_PROJECT_CREATE=0
ASSUME_YES=0

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
fail()  { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)          PROJECT_ID="$2"; shift 2 ;;
    --sa-name)             SA_NAME="$2"; shift 2 ;;
    --key-out)             KEY_OUT="$2"; shift 2 ;;
    --skip-project-create) SKIP_PROJECT_CREATE=1; shift ;;
    -y|--yes)              ASSUME_YES=1; shift ;;
    -h|--help)             usage 0 ;;
    *) fail "Unknown arg: $1 (use --help)" ;;
  esac
done

[[ -n "$PROJECT_ID" ]] || fail "--project-id is required."
[[ "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || \
  fail "Invalid --project-id '$PROJECT_ID' (must match [a-z][a-z0-9-]{4,28}[a-z0-9])."

echo "========================================="
echo " GCP Project & Service Account Creator"
echo "========================================="

# Preflight: gcloud present + authenticated
command -v gcloud >/dev/null 2>&1 || \
  fail "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
ACTIVE_ACCOUNT="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null || true)"
[[ -n "$ACTIVE_ACCOUNT" ]] || fail "No active gcloud account. Run: gcloud auth login"
echo "Authenticated as: $ACTIVE_ACCOUNT"

# Preflight: key output must not already exist (avoid key sprawl)
[[ -e "$KEY_OUT" ]] && fail "'$KEY_OUT' already exists. Remove it or pass a different --key-out."

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo
echo "About to create:"
echo "  GCP Project     : $PROJECT_ID $([[ $SKIP_PROJECT_CREATE -eq 1 ]] && echo '(use existing)')"
echo "  Service Account : $SA_EMAIL"
echo "  Key Output      : $KEY_OUT"
echo
if [[ $ASSUME_YES -ne 1 ]]; then
  read -r -p "Proceed? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
fi

if [[ $SKIP_PROJECT_CREATE -ne 1 ]]; then
  echo
  echo "Step 1: Creating GCP project '$PROJECT_ID'..."
  gcloud projects create "$PROJECT_ID" --name="SMIME Sync Project" || fail "Project creation failed."
fi

echo "Step 2: Setting active project..."
gcloud config set project "$PROJECT_ID" || fail "Could not set project."

echo "Step 3: Enabling Gmail API (may take ~60 s)..."
gcloud services enable gmail.googleapis.com --project="$PROJECT_ID" || fail "Failed to enable Gmail API."

echo "Step 4: Creating service account '$SA_NAME' (idempotent)..."
EXISTING="$(gcloud iam service-accounts list --project="$PROJECT_ID" \
  --filter="email:$SA_EMAIL" --format='value(email)' 2>/dev/null || true)"
if [[ -n "$EXISTING" ]]; then
  echo "  Service account already exists — skipping."
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="SMIME Sync Bot" --project="$PROJECT_ID" || fail "Service account creation failed."
  echo "Step 5: Waiting 15 s for SA propagation..."
  sleep 15
fi

echo "Step 6: Generating credentials key..."
gcloud iam service-accounts keys create "$KEY_OUT" \
  --iam-account="$SA_EMAIL" --project="$PROJECT_ID" || fail "Key generation failed."
[[ -f "$KEY_OUT" ]] || fail "Key file was not written."

# Extract client_id (python3 is present by default on macOS/Linux)
CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("client_id",""))' "$KEY_OUT" 2>/dev/null || true)"
[[ -n "$CLIENT_ID" ]] || fail "Key file exists but client_id is missing."

echo
echo "========================================="
echo " SUCCESS"
echo "========================================="
echo "  Client ID : $CLIENT_ID"
echo "  Key saved : $(cd "$(dirname "$KEY_OUT")" && pwd)/$(basename "$KEY_OUT")"
echo
echo "REQUIRED NEXT STEPS:"
echo "  1. Google Admin Console > Security > API Controls"
echo "     > Manage Domain-Wide Delegation > Add new"
echo "  2. Paste the Client ID above. Grant BOTH scopes:"
echo "     https://www.googleapis.com/auth/gmail.settings.basic"
echo "     https://www.googleapis.com/auth/gmail.settings.sharing"
echo "  3. Add the key file to .gitignore. Never commit it."
echo "  4. DWD changes can take up to 20 min to propagate."
