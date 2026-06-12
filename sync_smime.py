#!/usr/bin/env python3
"""
S/MIME Certificate Workspace Sync Script
Automates uploading S/MIME PKCS#12 certificates to Google Workspace via Gmail API.
Uses a GCP Service Account with Domain-Wide Delegation (DWD).
"""

import os
import sys
import argparse
import logging
import base64
import traceback
import csv
from datetime import datetime, timezone
from pathlib import Path

# Fix console encoding on Windows to prevent UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("smime_sync")

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtensionOID, NameOID
except ImportError:
    logger.error("Missing dependency: 'cryptography'. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    logger.error("Missing dependency: google-api-python-client / google-auth. Run: pip install -r requirements.txt")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.settings.sharing",
]

# Randomized exponential backoff applied by googleapiclient to transient
# failures (429 rate limits, 5xx). Important for bulk runs across many users.
API_NUM_RETRIES = 5

# Optional per-certificate password file expected in the certificate directory.
PASSWORD_MANIFEST_NAME = "passwords.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate loading of S/MIME IV certificates to Google Workspace."
    )
    parser.add_argument("--credentials", "-c", required=True,
                        help="Path to GCP Service Account JSON credentials file.")
    parser.add_argument("--directory", "-d", required=True,
                        help="Directory containing .p12 or .pfx certificate files.")
    parser.add_argument("--password", "-p", default=None,
                        help="PKCS#12 decryption password. Prefer SMIME_PASSWORD env var.")
    parser.add_argument("--password-csv", default=None,
                        help="Explicit path to a per-certificate password CSV (columns: "
                             "file and/or email, plus password). Overrides the auto-discovered "
                             "passwords.csv in the certificate directory.")
    parser.add_argument("--default", action="store_true",
                        help="Set uploaded certificate as default S/MIME key for the user.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate certificates locally without calling Google APIs.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging.")
    return parser.parse_args()


def extract_p12_info(p12_data: bytes, password: bytes) -> tuple:
    """
    Decrypts PKCS#12 bytes and extracts the owner email from SAN or CN.
    Returns (email_str, certificate_object, chain_list).
    `chain_list` holds any additional (intermediate/root) certificates bundled
    in the PFX — Google Workspace requires at least one intermediate.
    Raises ValueError if no email can be found.
    """
    private_key, certificate, chain = pkcs12.load_key_and_certificates(p12_data, password)

    if not certificate:
        raise ValueError("No certificate found inside the PKCS#12 file.")

    # 1. Try Subject Alternative Name (preferred)
    try:
        san_ext = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        emails = [n.value for n in san_ext.value if isinstance(n, x509.RFC822Name)]
        if emails:
            return emails[0].strip(), certificate, (chain or [])
    except x509.ExtensionNotFound:
        pass
    except Exception as exc:
        logger.debug("Failed extracting email from SAN: %s", exc)

    # 2. Fallback: Common Name containing @
    for attr in certificate.subject:
        if attr.oid == NameOID.COMMON_NAME:
            cn = attr.value.strip()
            if "@" in cn:
                return cn, certificate, (chain or [])

    raise ValueError("No valid email address found in SAN or CN of the certificate.")


def load_password_manifest(certs_dir: Path, explicit_path: Path | None = None) -> dict:
    """
    Reads a per-certificate password manifest and maps each certificate to its
    PKCS#12 password. Files not listed fall back to the global password.

    Source resolution:
      - If `explicit_path` is given (e.g. CLI --password-csv / GUI picker), it is
        used and must exist.
      - Otherwise an optional `passwords.csv` in `certs_dir` is auto-discovered.

    Accepted headers (case-insensitive): a `password` column plus at least one of
    `file` (certificate filename) and/or `email` (the address inside the cert).
    Both lookup keys are merged into a single mapping, so either a filename or an
    email-named file (e.g. `user@example.com.pfx`) resolves correctly. Returns {}
    if no manifest is present.
    """
    if explicit_path is not None:
        manifest_path = explicit_path
        if not manifest_path.exists():
            raise FileNotFoundError(f"Password CSV not found: {manifest_path}")
    else:
        manifest_path = certs_dir / PASSWORD_MANIFEST_NAME
        if not manifest_path.exists():
            return {}

    mapping: dict = {}
    # utf-8-sig strips the BOM that Excel prepends when saving CSVs.
    with open(manifest_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "password" not in headers:
            logger.warning(
                "%s found but missing a 'password' column — ignoring it.", manifest_path.name
            )
            return mapping
        if "file" not in headers and "email" not in headers:
            logger.warning(
                "%s found but has no 'file' or 'email' column — ignoring it.", manifest_path.name
            )
            return mapping
        for row in reader:
            row_l = {(k.strip().lower() if k else k): (v or "") for k, v in row.items()}
            pw = row_l.get("password", "")
            fname = row_l.get("file", "").strip()
            email = row_l.get("email", "").strip()
            if fname:
                mapping[fname] = pw
            if email:
                # Allow matching files literally named after the email.
                mapping[email] = pw

    logger.info("Loaded password manifest with %d entr%s.",
                len(mapping), "y" if len(mapping) == 1 else "ies")
    return mapping



def validate_credentials_file(credentials_path: Path) -> dict:
    """Loads and does a basic sanity-check on the service account JSON."""
    import json
    with open(credentials_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("type", "client_id", "client_email", "private_key"):
        if key not in data:
            raise ValueError(f"Credentials file is missing required field: '{key}'")
    if data.get("type") != "service_account":
        raise ValueError("Credentials file is not a service_account type.")
    return data


def process_certificate_file(
    file_path: Path,
    password: str,
    base_credentials,
    dry_run: bool,
    set_default: bool,
) -> dict:
    """
    Processes a single certificate: extract email, then upload to Google Workspace.
    `base_credentials` is a scoped service_account.Credentials object (loaded once
    by the caller); this function derives a per-user impersonation via with_subject().
    It is None during a dry-run. Returns a result dict with status/metadata/reason.
    """
    logger.info("Processing certificate: %s", file_path.name)

    result = {
        "file": file_path.name,
        "email": "",
        "subject": "",
        "valid_from": "",
        "valid_until": "",
        "status": "FAILED",
        "cert_id": "",
        "reason": "",
    }

    password_bytes = password.encode("utf-8") if password else None

    # ── Parse certificate ──────────────────────────────────────────────────────
    try:
        with open(file_path, "rb") as f:
            raw_data = f.read()
        email, cert, chain = extract_p12_info(raw_data, password_bytes)
        result["email"] = email
        result["subject"] = cert.subject.rfc4514_string()
        result["valid_from"] = str(cert.not_valid_before_utc)
        result["valid_until"] = str(cert.not_valid_after_utc)
        logger.info("  Extracted email : %s", email)
        logger.info("  Cert Subject    : %s", cert.subject.rfc4514_string())
        logger.info("  Valid From      : %s", cert.not_valid_before_utc)
        logger.info("  Valid Until     : %s", cert.not_valid_after_utc)
        logger.info("  Chain certs     : %d", len(chain))

        # Warn if cert is already expired
        if cert.not_valid_after_utc < datetime.now(timezone.utc):
            logger.warning("  Certificate is EXPIRED. Upload will likely be rejected by Google.")

        # Warn if no intermediate is bundled — the #1 cause of Workspace rejection.
        if not chain:
            logger.warning("  PFX contains NO chain certificates. Google Workspace "
                           "requires an intermediate CA; upload will likely be rejected.")

    except Exception as exc:
        result["reason"] = f"Parse error: {exc}"
        logger.error("  Failed parsing %s: %s", file_path.name, exc)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return result

    # ── Dry-run: stop here ─────────────────────────────────────────────────────
    if dry_run:
        result["status"] = "DRY-RUN"
        if not chain:
            result["reason"] = "Dry-run — WARNING: no intermediate chain in PFX (likely rejected)"
        else:
            result["reason"] = "Dry-run — no upload performed"
        logger.info("  [DRY-RUN] Would upload certificate for: %s", email)
        return result

    # ── Live upload ────────────────────────────────────────────────────────────
    try:
        creds = base_credentials.with_subject(email)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        smime_api = service.users().settings().sendAs().smimeInfo()

        # Retrieve sendAs list to confirm alias exists
        try:
            send_as_response = (
                service.users().settings().sendAs()
                .list(userId="me").execute(num_retries=API_NUM_RETRIES)
            )
        except HttpError as he:
            if he.resp.status == 403:
                result["reason"] = (
                    "403 Forbidden — check Domain-Wide Delegation is configured and "
                    f"user {email} exists in this Workspace tenant."
                )
                logger.error("  %s", result["reason"])
                return result
            raise

        send_as_entries = send_as_response.get("sendAs", [])
        matching_alias = next(
            (e["sendAsEmail"] for e in send_as_entries
             if e["sendAsEmail"].lower() == email.lower()),
            None,
        )

        if not matching_alias:
            available = [e["sendAsEmail"] for e in send_as_entries]
            result["reason"] = (
                f"Email '{email}' not found in sendAs. "
                f"Available aliases: {available}"
            )
            logger.error("  %s", result["reason"])
            return result

        # Idempotency: skip cleanly if this exact certificate is already present.
        # Comparing SHA-256 fingerprints avoids relying on Google's error wording.
        target_fp = cert.fingerprint(hashes.SHA256())
        try:
            existing = smime_api.list(
                userId="me", sendAsEmail=matching_alias
            ).execute(num_retries=API_NUM_RETRIES)
            for info in existing.get("smimeInfo", []):
                pem = info.get("pem")
                if not pem:
                    continue
                try:
                    existing_cert = x509.load_pem_x509_certificate(pem.encode("utf-8"))
                except Exception:
                    continue
                if existing_cert.fingerprint(hashes.SHA256()) == target_fp:
                    result["status"] = "ALREADY_EXISTS"
                    result["cert_id"] = info.get("id", "")
                    result["reason"] = "Certificate already uploaded — skipping."
                    logger.info("  Certificate already exists for %s — skipping.", matching_alias)
                    return result
        except HttpError as he:
            # Non-fatal: fall through to insert, which still guards duplicates below.
            logger.debug("  Could not list existing smimeInfo (%s); proceeding to insert.", he)

        # Build upload payload
        smime_body = {"pkcs12": base64.urlsafe_b64encode(raw_data).decode("utf-8")}
        if password:
            smime_body["encryptedKeyPassword"] = password

        # Insert S/MIME certificate
        logger.info("  Uploading S/MIME key for alias: %s ...", matching_alias)
        try:
            insert_result = smime_api.insert(
                userId="me", sendAsEmail=matching_alias, body=smime_body
            ).execute(num_retries=API_NUM_RETRIES)
        except HttpError as he:
            error_content = he.error_details if hasattr(he, "error_details") else str(he)
            if he.resp.status == 400:
                # Distinguish untrusted root CAs from duplicates
                if "already saved" in str(error_content).lower():
                    result["status"] = "ALREADY_EXISTS"
                    result["reason"] = "Certificate already uploaded — skipping."
                    logger.info("  Certificate already exists for %s — skipping.", matching_alias)
                    return result
                elif "not trusted" in str(error_content).lower():
                    result["reason"] = "The root certificate authority is not trusted by Google Workspace."
                    logger.error("  %s", result["reason"])
                    return result
                else:
                    result["reason"] = f"Bad Request (400): {error_content}"
                    logger.error("  Upload failed: %s", result["reason"])
                    return result
            elif he.resp.status == 403:
                result["reason"] = (
                    "S/MIME feature not enabled or insufficient licence. "
                    "Requires Google Workspace Enterprise Standard/Plus."
                )
                logger.error("  %s", result["reason"])
                return result
            else:
                result["reason"] = f"HttpError {he.resp.status}: {error_content}"
                logger.error("  Upload failed: %s", result["reason"])
                return result

        cert_id = insert_result.get("id", "")
        result["cert_id"] = cert_id
        logger.info("  Uploaded successfully. Cert ID: %s", cert_id)

        # Optionally set as default
        if set_default and cert_id:
            logger.info("  Setting cert %s as default...", cert_id)
            smime_api.setDefault(
                userId="me", sendAsEmail=matching_alias, id=cert_id
            ).execute(num_retries=API_NUM_RETRIES)
            logger.info("  Set as default successfully.")

        result["status"] = "SUCCESS"
        result["reason"] = "Uploaded and set as default" if set_default else "Uploaded"

    except Exception as exc:
        if not result["reason"]:
            result["reason"] = str(exc)
        logger.error("  Unexpected error for %s: %s", email, exc)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()

    return result


def write_csv_report(results: list, output_dir: Path) -> Path:
    """Writes a timestamped CSV report to output_dir."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"smime_sync_report_{timestamp}.csv"
    fieldnames = ["file", "email", "status", "reason", "cert_id", "valid_from", "valid_until", "subject"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    logger.info("CSV report saved: %s", csv_path)
    return csv_path


def run_sync(
    certs_dir: Path,
    credentials_path: str | None,
    password: str,
    dry_run: bool,
    set_default: bool,
    password_csv: Path | None = None,
) -> dict:
    """
    Scans certs_dir for .p12/.pfx files and uploads each to Google Workspace.
    Loads service-account credentials once and impersonates per-user, applies a
    per-certificate password manifest (passwords.csv) with global fallback, and
    writes a CSV report on live runs.

    Shared by the CLI (main) and the GUI worker. Returns a summary dict:
    {"results", "success", "failed", "already", "total"}. Raises on
    unrecoverable setup errors (e.g. invalid credentials) so callers can abort.
    """
    logger.info("=" * 50)
    logger.info("Starting S/MIME Google Workspace Sync")
    logger.info("Directory   : %s", certs_dir.resolve())
    if dry_run:
        logger.info("MODE        : DRY-RUN (local validation only)")
    else:
        logger.info("Credentials : %s", Path(credentials_path).resolve())
    logger.info("=" * 50)

    empty = {"results": [], "success": 0, "failed": 0, "already": 0, "total": 0}

    # ── Scan for certificate files ─────────────────────────────────────────────
    cert_files: list[Path] = []
    for ext in ("*.p12", "*.pfx"):
        cert_files.extend(certs_dir.glob(ext))

    if not cert_files:
        logger.warning("No .p12 or .pfx files found in: %s", certs_dir.resolve())
        return empty

    logger.info("Found %d certificate file(s).", len(cert_files))

    # Per-certificate passwords (filename/email -> password), with global fallback.
    # An explicit --password-csv (password_csv) overrides the auto-discovered
    # passwords.csv inside certs_dir.
    password_map = load_password_manifest(certs_dir, explicit_path=password_csv)

    # Load service-account credentials ONCE; per-user impersonation is derived
    # later via with_subject(), avoiding a disk read/parse per certificate.
    base_credentials = None
    if not dry_run:
        validate_credentials_file(Path(credentials_path))
        base_credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )

    results = []
    success_count = 0
    fail_count = 0
    already_count = 0

    for file_path in sorted(cert_files):
        # Match by exact filename first, then by stem (covers files literally
        # named after the email, e.g. user@example.com.pfx), else global password.
        file_password = password_map.get(
            file_path.name,
            password_map.get(file_path.stem, password),
        )
        result = process_certificate_file(
            file_path=file_path,
            password=file_password,
            base_credentials=base_credentials,
            dry_run=dry_run,
            set_default=set_default,
        )
        results.append(result)

        if result["status"] in ("SUCCESS", "DRY-RUN"):
            success_count += 1
        elif result["status"] == "ALREADY_EXISTS":
            already_count += 1
            success_count += 1
        else:
            fail_count += 1

    # ── Print summary ──────────────────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Sync Execution Report:")
    logger.info("  Total Processed : %d", len(cert_files))
    already_note = f" ({already_count} already existed)" if already_count else ""
    logger.info("  Successful      : %d%s", success_count, already_note)
    logger.info("  Failed          : %d", fail_count)
    for r in results:
        if r["status"] in ("SUCCESS", "ALREADY_EXISTS"):
            icon = "+"
        elif r["status"] == "DRY-RUN":
            icon = "~"
        else:
            icon = "x"
        logger.info("  [%s] %-40s %s  %s", icon, r["email"] or r["file"], r["status"], r["reason"])
    logger.info("=" * 50)

    if not dry_run:
        write_csv_report(results, certs_dir)

    return {
        "results": results,
        "success": success_count,
        "failed": fail_count,
        "already": already_count,
        "total": len(cert_files),
    }


def main() -> None:
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Password: CLI arg takes precedence over env var
    password = args.password or os.environ.get("SMIME_PASSWORD", "") or ""

    # ── Validate inputs ────────────────────────────────────────────────────────
    certs_dir = Path(args.directory)
    if not certs_dir.exists() or not certs_dir.is_dir():
        logger.error("Certificates directory not found: %s", args.directory)
        sys.exit(1)

    credentials_path = Path(args.credentials)
    if not args.dry_run and not credentials_path.exists():
        logger.error("Credentials file not found: %s", args.credentials)
        sys.exit(1)

    password_csv = Path(args.password_csv) if args.password_csv else None
    if password_csv and not password_csv.exists():
        logger.error("Password CSV not found: %s", args.password_csv)
        sys.exit(1)

    try:
        summary = run_sync(
            certs_dir=certs_dir,
            credentials_path=str(credentials_path),
            password=password,
            dry_run=args.dry_run,
            set_default=args.default,
            password_csv=password_csv,
        )
    except Exception as exc:
        logger.error("Sync aborted: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        sys.exit(1)

    sys.exit(1 if summary["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
