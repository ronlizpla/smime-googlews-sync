#!/usr/bin/env python3
"""
S/MIME Certificate Workspace Sync Script
Automates the loading of S/MIME PKCS#12 certificates to Google Workspace.
Uses Google GCP Service Account with Domain-Wide Delegation.
"""

import os
import sys
import argparse
import logging
import base64
import traceback
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("smime_sync")

try:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtensionOID, NameOID
except ImportError:
    logger.error("Missing dependency: 'cryptography'. Please run 'pip install -r requirements.txt'")
    sys.exit(1)

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    logger.error("Missing dependency: 'google-api-python-client' or 'google-auth'. Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Scopes needed for S/MIME and send-as settings management
SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.settings.sharing"
]

def parse_args():
    parser = argparse.ArgumentParser(
        description="Automate loading of S/MIME IV certificates to Google Workspace."
    )
    parser.add_argument(
        "--credentials", "-c",
        required=True,
        help="Path to the Google Cloud Service Account JSON credentials file."
    )
    parser.add_argument(
        "--directory", "-d",
        required=True,
        help="Directory containing S/MIME PKCS#12 certificates (.p12 or .pfx)."
    )
    parser.add_argument(
        "--password", "-p",
        help="Password to decrypt the PKCS#12 files. Can also be set via the SMIME_PASSWORD environment variable."
    )
    parser.add_argument(
        "--default", action="store_true",
        help="Set the uploaded S/MIME certificate as the default certificate for the user's alias."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Verify credentials and certificates locally without calling Google APIs."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable detailed debug logs."
    )
    return parser.parse_args()

def extract_email_from_p12(file_path: Path, password: bytes) -> tuple:
    """
    Decrypts the PKCS#12 file and extracts the email address from Subject Alternative Name (SAN) or Common Name (CN).
    Returns (email, certificate_object) or raises ValueError/Exception.
    """
    with open(file_path, "rb") as f:
        p12_data = f.read()

    # Load certificate and private key
    # pkcs12.load_key_and_certificates returns (private_key, certificate, additional_certificates)
    private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
        p12_data, password
    )

    if not certificate:
        raise ValueError("No certificate found inside the PKCS#12 file.")

    # 1. Try Subject Alternative Name (SAN)
    try:
        san_ext = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        emails = [name.value for name in san_ext.value if isinstance(name, x509.RFC822Name)]
        if emails:
            return emails[0].strip(), certificate
    except x509.ExtensionNotFound:
        pass
    except Exception as e:
        logger.debug(f"Failed extracting email from SAN for {file_path.name}: {e}")

    # 2. Fallback to Common Name (CN)
    for attribute in certificate.subject:
        if attribute.oid == NameOID.COMMON_NAME:
            cn_value = attribute.value.strip()
            if "@" in cn_value:
                return cn_value, certificate

    raise ValueError("Could not find a valid email address in SAN or CN of the certificate.")

def process_certificate_file(file_path: Path, password: str, credentials_path: str, dry_run: bool, set_default: bool):
    """
    Processes a single certificate: extracts email, verifies credentials, and uploads to Google Workspace.
    """
    logger.info(f"Processing certificate: {file_path.name}")
    
    password_bytes = password.encode("utf-8") if password else None
    
    try:
        email, cert = extract_email_from_p12(file_path, password_bytes)
        logger.info(f"  Extracted owner email: {email}")
        logger.info(f"  Cert Subject: {cert.subject.rfc4514_string()}")
        logger.info(f"  Valid From:   {cert.not_valid_before_utc}")
        logger.info(f"  Valid Until:  {cert.not_valid_after_utc}")
    except Exception as e:
        logger.error(f"  Failed parsing certificate {file_path.name}: {e}")
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return False

    if dry_run:
        logger.info(f"  [DRY-RUN] Would upload certificate for user: {email}")
        return True

    # Run the actual API calls
    try:
        # Build the Google service impersonating the user
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=SCOPES,
            subject=email
        )
        service = build("gmail", "v1", credentials=creds)

        # Retrieve user's sendAs configurations to find the matching email / alias
        try:
            send_as_response = service.users().settings().sendAs().list(userId="me").execute()
        except HttpError as he:
            if he.resp.status == 403:
                logger.error(f"  Permission denied: Ensure Domain-Wide Delegation is set up for scope settings and the user {email} exists.")
            raise he

        send_as_entries = send_as_response.get("sendAs", [])
        matching_alias = None
        for entry in send_as_entries:
            if entry["sendAsEmail"].lower() == email.lower():
                matching_alias = entry["sendAsEmail"]
                break

        if not matching_alias:
            available_aliases = [e["sendAsEmail"] for e in send_as_entries]
            raise ValueError(
                f"Email address '{email}' not found in user's SendAs configurations. "
                f"Available aliases: {available_aliases}"
            )

        # Read file bytes for uploading
        with open(file_path, "rb") as f:
            raw_data = f.read()
        
        # Base64url-encode the PKCS#12 payload as required by Google API
        b64_payload = base64.urlsafe_b64encode(raw_data).decode("utf-8")

        # Construct SmimeInfo resource
        smime_body = {
            "pkcs12": b64_payload
        }
        if password:
            smime_body["encryptedKeyPassword"] = password

        # Insert S/MIME certificate
        logger.info(f"  Uploading S/MIME key to Gmail for alias: {matching_alias}...")
        insert_result = service.users().settings().sendAs().smimeInfo().insert(
            userId="me",
            sendAsEmail=matching_alias,
            body=smime_body
        ).execute()

        cert_id = insert_result.get("id")
        logger.info(f"  Successfully uploaded certificate! ID: {cert_id}")

        # Set as default if requested
        if set_default:
            logger.info(f"  Setting certificate {cert_id} as default S/MIME key...")
            service.users().settings().sendAs().smimeInfo().setDefault(
                userId="me",
                sendAsEmail=matching_alias,
                id=cert_id
            ).execute()
            logger.info("  Set as default successfully.")

        return True

    except Exception as e:
        logger.error(f"  Failed uploading certificate for {email}: {e}")
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return False

def main():
    args = parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        
    password = args.password or os.environ.get("SMIME_PASSWORD", "")
    
    # Validate directories and credentials
    certs_dir = Path(args.directory)
    if not certs_dir.exists() or not certs_dir.is_dir():
        logger.error(f"Certificates directory not found: {args.directory}")
        sys.exit(1)
        
    credentials_path = Path(args.credentials)
    if not args.dry_run and not credentials_path.exists():
        logger.error(f"Credentials JSON file not found: {args.credentials}")
        sys.exit(1)

    logger.info("==================================================")
    logger.info("Starting S/MIME Google Workspace Sync Script")
    logger.info(f"Directory: {certs_dir.resolve()}")
    if args.dry_run:
        logger.info("MODE: DRY-RUN (Local validations only)")
    else:
        logger.info(f"Credentials: {credentials_path.resolve()}")
    logger.info("==================================================")

    # Scan for certificate files
    extensions = ("*.p12", "*.pfx")
    cert_files = []
    for ext in extensions:
        cert_files.extend(certs_dir.glob(ext))

    if not cert_files:
        logger.warning(f"No .p12 or .pfx files found in {certs_dir.resolve()}")
        sys.exit(0)

    logger.info(f"Found {len(cert_files)} certificate file(s).")
    
    success_count = 0
    fail_count = 0

    for file_path in cert_files:
        success = process_certificate_file(
            file_path=file_path,
            password=password,
            credentials_path=str(credentials_path),
            dry_run=args.dry_run,
            set_default=args.default
        )
        if success:
            success_count += 1
        else:
            fail_count += 1

    logger.info("==================================================")
    logger.info("Sync Execution Report:")
    logger.info(f"  Total Processed: {len(cert_files)}")
    logger.info(f"  Successful:      {success_count}")
    logger.info(f"  Failed:          {fail_count}")
    logger.info("==================================================")

    if fail_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
