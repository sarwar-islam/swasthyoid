# Decision log

P0 exit gate (FRD section 11): all five decisions below recorded.
Questions are copied from FRD section 12. Options are listed only where the FRD names them.

## Q1 — Which drug catalog source can we legally use, and on what terms?

- **Status:** OPEN
- **Options:** not listed in the FRD. Note (FRD section 12): do not reuse MedBangla AI code or catalog until its author confirms licence and origin in writing.
- **Decision:**
- **Owner:**
- **Date:**

## Q2 — MongoDB + Qdrant, or one PostgreSQL with pgvector and pg_trgm?

- **Status:** DECIDED
- **Options:** (a) MongoDB + Qdrant; (b) one PostgreSQL with pgvector and pg_trgm
- **Decision:** (b) one PostgreSQL. pgvector and pg_trgm are added when P3 needs them.
- **Owner:** Sarwar Islam
- **Date:** 2026-11-11

## Q4 — Where is the system hosted, and must health data stay in Bangladesh?

- **Status:** OPEN
- **Options:** not listed in the FRD
- **Decision:**
- **Owner:**
- **Date:**

## Q5 — Which cloud AI provider and terms, or local-only?

- **Status:** OPEN
- **Options:** (a) a cloud AI provider (which one, on what terms; patient opt-in only); (b) local-only
- **Decision:**
- **Owner:**
- **Date:**

## Q7 — Which clinician signs off rules, red flags, thresholds and emergency messages?

- **Status:** OPEN
- **Options:** a named clinical reviewer
- **Decision:**
- **Owner:**
- **Date:**

---

# Caregiver access (P2 architecture change)

Approved by Sarwar Islam, 2026-11-12. Elderly and digitally inexperienced patients may be
helped by a caregiver. This is not in the FRD yet; the FRD changes it needs are listed below.

## Decided

- A caregiver authorization is a consent: purpose `CAREGIVER` in the existing `consents` table,
  judged by the existing C1 engine and audited by C2. No separate permission system.
- A caregiver is an ordinary person account and logs in with their own phone.
- Scopes, each granted separately: `upload_documents`, `view_documents`, `view_timeline`.
- The patient is the only source of authorization, either signed in to the app or by reading
  out a code sent to the patient's own phone. The caregiver can only ask.
- Scopes never change on an existing authorization. More scopes or more time is a new request
  with a new approval, which replaces the old authorization in one transaction.
- One active and one pending authorization per patient-caregiver pair, enforced by the database.
- Verification stays patient-only. Caregivers cannot verify, and no clinical trust is placed in
  caregiver-confirmed data. The database refuses a caregiver verification scope.
- `DEV_LOG_CODES` defaults to 0. Codes are logged only with `DEV_LOG_CODES=1` and
  `APP_ENV=development`; the application refuses to start with the flag set in any other
  environment. Automated tests use mocked delivery.

## Provisional (to be confirmed against the FRD)

| Setting | Value | Where |
|---|---|---|
| Default duration | 30 days | `core/consent_authz.py` |
| Maximum duration, no permanent authorization | 90 days | `core/consent_authz.py` and the `caregiver_shape` constraint in `core/schema.sql` |
| Renewal | explicit new request and approval | by design |
| Unapproved request closes after | 24 hours, enforced at request time | `core/consent_authz.py` |

## Configurable security defaults (not FRD values)

| Setting | Value | Where |
|---|---|---|
| Code lifetime | 5 minutes | `identity/otp.py` |
| Wrong guesses before a code is dead | 5 | `identity/otp.py` |
| Codes per patient phone, per kind | 5 per 15 minutes | `identity/otp.py` |
| Codes per caregiver request | 3 | `api/caregivers.py` |
| Requests per caregiver (hits and misses alike) | 5 per 15 minutes | `api/caregivers.py` |
| Minimum response time for request and confirm | 0.3 s | `api/caregivers.py` |
| Idempotency-Key retention | 24 hours | `api/deps.py` |

## FRD changes required

- **4.1 consent purposes:** add `CAREGIVER` (grantee: caregiver; bound to patient and caregiver;
  scope: the three permissions above; activates on patient approval; ends on expiry, revoke or
  replacement).
- **4.1 consent state machine:** add `pending --> declined : patient declines` and
  `declined --> [*]`. `declined` (the patient said no) is distinct from `expired` (nobody answered).
- **Section 2 roles:** add the caregiver, with can/cannot (cannot verify, grant, revoke or read
  access history for the patient).
- **Section 7 API:** add the `/caregiver-authorizations` endpoints.
- **ERD A:** `consents.requested_ttl`; `consents.grantee_id` may reference a person account.
- **ERD D:** `idempotency_keys` is keyed by caller, endpoint and key, and stores a keyed hash.

## Future requirement, not implemented

- **Assisted registration.** A patient with no phone or no account cannot be helped by this
  design, because every authorization needs the patient's own approval. A separate
  assisted-registration flow (for example staff-assisted, with identity checks) is needed and
  must be designed before it is built. Related: FRD open question 12 (minors and guardians).
