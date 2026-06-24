# SSL.com SWS API — implementation notes

Source: OpenAPI spec **SSL.com / ssl_certificate_api / 1.0.0**
<https://api.swaggerhub.com/apis/SSL.com/ssl_certificate_api/1.0.0>

## Base URLs
| Env | URL |
|-----|-----|
| Production | `https://sws.sslpki.com` |
| Sandbox/test | `https://sws-test.sslpki.com` |

## Auth
`account_key` + `secret_key` sent as **query parameters** on every request.

## Endpoints used
| Method | Path | Use |
|--------|------|-----|
| GET | `/certificates` | List orders |
| POST | `/certificates` | Create order — returns top-level `ref` |
| GET | `/certificate/{ref}` | Status + download; PEM bundle in `certificates` |
| PUT | `/certificate/{ref}` | Process/rekey/**change or re-trigger DCV method** |
| DELETE | `/certificate/{ref}` | Revoke |
| POST | `/certificates/validations/email` | Acceptable approver emails per domain |
| GET | `/certificate/{ref}/api_parameters/{action}` | Pre-filled params helper |

## Personal / S/MIME product codes
`300` Personal Basic · `301` Person Pro · `302` Personal Business · `303` Personal Enterprise

## Periods (days)
`365, 730, 1095, 1461, 1826` for these products.

## GET /certificate/{ref}
- Query: `response_type` = `individually` (default) | `zip` | `netscape` | `pkcs7`;
  `response_encoding` = `base64` (default) | `binary`.
- Returns `order_status`, `certificates` (leaf **+ intermediate chain** PEM,
  concatenated), `common_name`, `subject_alternative_names`, `validations`
  (`{domain: {dcv_method, status, attempted_on}}`), `effective_date`,
  `expiration_date`.

## DCV automation — what the API can and cannot do
- ✅ List approver emails: `POST /certificates/validations/email`.
- ✅ Set/choose DCV method at order time via `domains` object.
- ✅ Re-trigger / change DCV via `PUT /certificate/{ref}` (re-set `domains`).
- ✅ Poll status via `GET /certificate/{ref}` → `validations[*].status`.
- ❌ **No endpoint to approve/complete DCV.** The final approval (clicking the
  link in SSL.com's validation email) is manual. The tool polls and reports it.

## ⚠ TO VERIFY IN SANDBOX (isolated as constants in `sslcom_client.py`)
The spec is written for SSL/domain certs. Before production, place ONE test
order against `sws-test.sslpki.com` and confirm:
1. **Subject email** — that SSL.com honours the email we put in the CSR Subject
   (`emailAddress`) + SAN `rfc822Name` for Personal products. (No documented
   subject-email field exists in `CreateCertificateApiRequest`.)
2. **Email DCV shape** — how email DCV is requested for a *mailbox* (vs a
   hostname). We currently send `domains: {email: {"dcv": email}}`. Confirm via a
   sandbox order and/or `GET /certificate/{ref}/api_parameters/create_w_csr` /
   `dcv_emails`. Adjust `DCV_EMAIL_KEY` / `build_order_body` if different.
3. **Product code** — confirm which Personal product (300–303) you are entitled
   to order; set `SMIME_PRODUCT_CODE` / pass `--product`.
4. **Chain presence** — confirm the issued `certificates` bundle includes the
   intermediate (Google Workspace rejects leaf-only chains).

## ✅ VERIFIED IN SANDBOX (2026-06-16)

Live testing against `sws-test.sslpki.com` resolved the open questions.

### Product
- **600 = `ov-smime`** ("Organization Only Email"), an OV S/MIME product — now
  the tool default (`SMIME_PRODUCT_CODE`). $38 in sandbox. Codes 300-303 also
  exist. Order this product for Workspace S/MIME.

### CSR must use LF line endings (the hardest bug)
- CSR PEM with **CRLF (`\r\n`) -> HTTP 500** `"server error"`.
- `base64(PEM)` -> HTTP 400 `"csr has problems"`.
- CSR PEM with **LF (`\n`) only -> HTTP 200**. The tool now force-normalizes
  the CSR to LF in `generate_key_and_csr`.

### Subject email handling - CONFIRMED
- Email in the CSR Subject (`emailAddress`) + SAN `rfc822Name` works: the API
  parsed it into the validation target `email:alice@example.com`. The CSR's CN
  also becomes a separate validation item, so prefer setting CN to the email.

### Order lifecycle (confirmed end-to-end)
1. `POST /certificates` {product:600, period:365} -> `ref`, status
   *"unused. waiting on certificate signing request (csr)"*.
2. `PUT /certificate/{ref}` {csr (LF!)} -> *"waiting on registrant information
   from customer"*; API echoes parsed `domains` / `validations` items.
3. `PUT /certificate/{ref}` {domains:{ "email:<addr>": {dcv:"<addr>"} }} ->
   *"validating, please wait"* (DCV email triggered).
4. Human approves the DCV email (+ OV org validation) -> issued.
5. `GET /certificate/{ref}` -> `certificates` PEM bundle (leaf + chain).

### Auth
- `account_key`/`secret_key` accepted **both** in the JSON body and as query
  params. The tool sends them as query params (spec-compliant).

### Helper endpoint
- `GET /certificate/{ref}/api_parameters/update` returns the exact fields the
  next call expects (`server_software`, `domains`, `contacts`, `csr`). Several
  other actions 500 in sandbox; `update` and `update_dcv` are reliable.

### Status strings are prose, not enums
- e.g. *"validating, please wait"*. Match issuance by substring, not equality.

### Still to confirm
- **OV registrant/org fields** required before issuance (status reached
  *"waiting on registrant information"*); the OV org validation is manual.
- The final issued **chain contents** (need a fully-issued sandbox order to see
  the `certificates` bundle and confirm the intermediate is included).

## ✅ ROUND 2 (2026-06-16) — full product map + registrant flow

### Product map (probed live)
| Code | product_name | Description |
|------|--------------|-------------|
| 300 | personal-basic | 1 Year Personal Basic |
| 301 | personal-pro | 1 Year Personal Pro |
| 302 | personal-business | 1 Year Personal Business |
| 303 | personal-enterprise | 1 Year Personal Enterprise |
| 400 | iv-codesigning | Personal ID Code Signing |
| 500 | iv-document | Personal ID Document Signing |
| 600 | ov-smime | Organization Only Email *(tool default)* |
| 700 | iv-ov-smime | Personal ID + Organization Email |

Codes 401/501/601/602 → HTTP 400 (not valid).

### Verified order flow (now implemented in the tool)
1. `POST /certificates` {product, period}  → order ref (NO csr — voucher state).
2. `PUT /certificate/{ref}` {csr (LF), registrant fields, contacts}
   → *"waiting on validation from customer"*.
3. `PUT /certificate/{ref}` {domains:{ <item>:{dcv:<email>} }}
   → *"validating, please wait"*.
4. Human approves DCV email (+ OV org validation) → issued.
5. `GET /certificate/{ref}` → `certificates` PEM bundle.

⚠ Doing csr + registrant in the single POST returns **HTTP 500**. The CSR must
be submitted via the PUT after the order exists.

### Registrant fields (echoed by the order's `registrant` object)
`organization`, `organization_unit`, `street_address_1/2/3`, `locality`,
`state_or_province` (response) / `state_or_providence` (request), `post_office_box`,
`postal_code`, `country`, `email`, plus OV-only: `assumed_name`, `company_number`,
`business_category`, `organization_identifier`, `duns_number`,
`incorporation_country/date/state/city`.

**Even Personal products (300) require registrant info** before issuance.

### No product auto-issues in sandbox
Every product (300, 600, …) parks at *"validating, please wait"* until the DCV
email is approved — there is no way to obtain a fully-issued cert (and thus a
real `.p12`) without the manual approval click. The `.p12` build/split path is
verified with a synthetic chain; a real end-to-end `.p12` needs one approved order.
