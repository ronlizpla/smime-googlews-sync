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
    parser.add_argument("--default", action="store_true",
                        help="Set uploaded certificate as default S/MIME key for the user.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and validate certificates locally without calling Google APIs.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging.")
    return parser.parse_args()


def extract_email_from_p12(file_path: Path, password: bytes) -> tuple:
    """
    Decrypts a PKCS#12 file and extracts the owner email from SAN or CN.
    Returns (email_str, certificate_object).
    Raises ValueError if no email can be found.
    """
    with open(file_path, "rb") as f:
        p12_data = f.read()

    private_key, certificate, _chain = pkcs12.load_key_and_certificates(p12_data, password)

    if not certificate:
        raise ValueError("No certificate found inside the PKCS#12 file.")

    # 1. Try Subject Alternative Name (preferred)
    try:
        san_ext = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        emails = [n.value for n in san_ext.value if isinstance(n, x509.RFC822Name)]
        if emails:
            return emails[0].strip(), certificate
    except x509.ExtensionNotFound:
        pass
    except Exception as exc:
        logger.debug("Failed extracting email from SAN for %s: %s", file_path.name, exc)

    # 2. Fallback: Common Name containing @
    for attr in certificate.subject:
        if attr.oid == NameOID.COMMON_NAME:
            cn = attr.value.strip()
            if "@" in cn:
                return cn, certificate

    raise ValueError("No valid email address found in SAN or CN of the certificate.")


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
    credentials_path: str,
    dry_run: bool,
    set_default: bool,
) -> dict:
    """
    Processes a single certificate: extract email, then upload to Google Workspace.
    Returns a result dict with status, email, cert metadata, and reason.
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
        email, cert = extract_email_from_p12(file_path, password_bytes)
        result["email"] = email
        result["subject"] = cert.subject.rfc4514_string()
        result["valid_from"] = str(cert.not_valid_before_utc)
        result["valid_until"] = str(cert.not_valid_after_utc)
        logger.info("  Extracted email : %s", email)
        logger.info("  Cert Subject    : %s", cert.subject.rfc4514_string())
        logger.info("  Valid From      : %s", cert.not_valid_before_utc)
        logger.info("  Valid Until     : %s", cert.not_valid_after_utc)

        # Warn if cert is already expired
        if cert.not_valid_after_utc < datetime.now(timezone.utc):
            logger.warning("  Certificate is EXPIRED. Upload will likely be rejected by Google.")

    except Exception as exc:
        result["reason"] = f"Parse error: {exc}"
        logger.error("  Failed parsing %s: %s", file_path.name, exc)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return result

    # ── Dry-run: stop here ─────────────────────────────────────────────────────
    if dry_run:
        result["status"] = "DRY-RUN"
        result["reason"] = "Dry-run — no upload performed"
        logger.info("  [DRY-RUN] Would upload certificate for: %s", email)
        return result

    # ── Live upload ────────────────────────────────────────────────────────────
    try:
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=SCOPES,
            subject=email,
        )
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # Retrieve sendAs list to confirm alias exists
        try:
            send_as_response = service.users().settings().sendAs().list(userId="me").execute()
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

        # Build upload payload
        with open(file_path, "rb") as f:
            raw_data = f.read()

        smime_body = {"pkcs12": base64.urlsafe_b64encode(raw_data).decode("utf-8")}
        if password:
            smime_body["encryptedKeyPassword"] = password

        # Insert S/MIME certificate
        logger.info("  Uploading S/MIME key for alias: %s ...", matching_alias)
        try:
            insert_result = (
                service.users().settings().sendAs().smimeInfo()
                .insert(userId="me", sendAsEmail=matching_alias, body=smime_body)
                .execute()
            )
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
            service.users().settings().sendAs().smimeInfo().setDefault(
                userId="me", sendAsEmail=matching_alias, id=cert_id
            ).execute()
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
    if not args.dry_run:
        if not credentials_path.exists():
            logger.error("Credentials file not found: %s", args.credentials)
            sys.exit(1)
        try:
            creds_info = validate_credentials_file(credentials_path)
            logger.info("Credentials validated. Client ID: %s", creds_info["client_id"])
        except (ValueError, Exception) as exc:
            logger.error("Credentials file is invalid: %s", exc)
            sys.exit(1)

    logger.info("=" * 50)
    logger.info("Starting S/MIME Google Workspace Sync Script")
    logger.info("Directory   : %s", certs_dir.resolve())
    if args.dry_run:
        logger.info("MODE        : DRY-RUN (local validation only)")
    else:
        logger.info("Credentials : %s", credentials_path.resolve())
    logger.info("=" * 50)

    # ── Scan for certificate files ─────────────────────────────────────────────
    cert_files: list[Path] = []
    for ext in ("*.p12", "*.pfx"):
        cert_files.extend(certs_dir.glob(ext))

    if not cert_files:
        logger.warning("No .p12 or .pfx files found in: %s", certs_dir.resolve())
        sys.exit(0)

    logger.info("Found %d certificate file(s).", len(cert_files))

    results = []
    success_count = 0
    fail_count = 0
    already_count = 0

    for file_path in sorted(cert_files):
        result = process_certificate_file(
            file_path=file_path,
            password=password,
            credentials_path=str(credentials_path),
            dry_run=args.dry_run,
            set_default=args.default,
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

    if not args.dry_run:
        write_csv_report(results, certs_dir)

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
