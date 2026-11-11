# SwasthyoID — Functional Requirements & Architecture (v2)

**Date:** 11 November 2026
**Principle:** *AI reads → Human verifies → Rules check → Doctor decides → Every access is consented and audited.*

> All diagrams are written in **Mermaid**. They render on GitHub, GitLab, VS Code (Markdown Preview Mermaid Support extension), Obsidian, Notion, or by pasting a block into https://mermaid.live.

## Contents

1. Purpose, scope, invariants
2. Actors and roles
3. System architecture (context, layered, module map, deployment)
4. Shared core services (C1 Consent and Authorization, C2 Audit, C3 Notification, C4 Event and Provenance)
5. Modules M1–M13 (functionality, rules, sequence and state diagrams)
6. Data model (overview ERD + detailed ERDs)
7. API summary
8. AI pipeline
9. Non-functional requirements
10. Edge cases and test matrix
11. Roadmap (fixed, fresh)
12. Open questions
13. Repository layout

---

## 1. Purpose, scope, invariants

### 1.1 Purpose
SwasthyoID turns the paper prescriptions and lab reports a patient already holds into a **verified, consent-controlled, patient-owned health record**. Doctors get a one-minute timeline summary. Referrals, appointments, pharmacy dispensing and emergencies share only the data the patient allows. Medicines are checked with clinician-approved rules. Patients can also log home BP and glucose, clearly labelled as patient-reported.

### 1.2 Scope
**In scope (prototype and pilot):** thirteen modules M1–M13 and four shared core services C1–C4.

**Out of scope:** diagnosis or dosing advice, replacing a hospital information system, selling or sharing data with pharma, payments, wearables and device-verified vitals, genomics, medical-image diagnosis.

### 1.3 Invariants (every module must keep these)

| # | Invariant |
|---|---|
| 1 | Data read from paper enters the timeline only after human verification. Patient-reported data may enter, but always labelled `patient_reported`, never shown as verified. |
| 2 | Safety alerts, red flags, vital thresholds and emergency messages come only from deterministic, clinician-approved rules. An LLM never decides them. |
| 3 | Summaries are generated from timeline events only. Every sentence cites events, and a code validator rejects unsupported content. |
| 4 | Every read by anyone other than the patient is authorized by C1 (one consent engine) and written to C2 (audit). No module has its own consent check. |
| 5 | Events and audit entries are append-only. A correction is a new event that supersedes the old one. |
| 6 | An alert is never a diagnosis, and no alert never means safe. |
| 7 | Notification failure never loses a health event or an audit record. |
| 8 | Safety paths fail closed: rule load error, audit failure or authorization outage blocks access or the check, never an empty pass. Only triage and emergency have their own fail-safe fallbacks. |
| 9 | Development and tests use synthetic data only. |

### 1.4 Prototype acceptance scenario (end to end, synthetic data)
1. Photograph a prescription, 2. OCR extracts it, 3. a human verifies it, 4. it appears on the timeline, 5. a new prescription triggers a drug-conflict alert, 6. the patient books an appointment with consent and the doctor opens the summary after check-in, 7. a referral snapshot is sent and feedback returns, 8. the patient logs home BP and it appears labelled patient-reported.

---

## 2. Actors and roles

```mermaid
flowchart LR
    P["Patient"]
    D["Doctor"]
    RD["Receiving Doctor"]
    ED["Emergency-enabled Doctor"]
    PH["Pharmacist"]
    V["Verifier (staff or CHW)"]
    CR["Clinical Reviewer"]
    A["Admin"]

    subgraph UC["SwasthyoID use cases"]
        U1["Upload and verify documents"]
        U2["Grant, view and revoke consent"]
        U3["View own timeline and access history"]
        U4["Log home vitals"]
        U5["Book appointment and check in"]
        U6["Approve referral"]
        U7["Read summary and timeline with consent"]
        U8["Write e-prescription and run safety check"]
        U9["Create referral"]
        U10["Read referral snapshot and submit feedback"]
        U11["Dispense against a prescription"]
        U12["Break-glass emergency card"]
        U13["Capture and verify on behalf of patient"]
        U14["Author and approve rules and thresholds"]
        U15["Approve credentials, import catalog, export audit"]
    end

    P --> U1
    P --> U2
    P --> U3
    P --> U4
    P --> U5
    P --> U6
    D --> U7
    D --> U8
    D --> U9
    RD --> U10
    PH --> U11
    ED --> U12
    V --> U13
    CR --> U14
    A --> U15
```

| Role | Can do | Cannot do |
|---|---|---|
| **Patient** (phone OTP) | Upload, verify own extractions, view own timeline and access history, grant/revoke consent, log vitals, reminders, triage, set emergency profile | See other patients |
| **Doctor** (BMDC verified, admin approved) | Request consent, read summary/timeline under consent, e-prescribe, safety check, ack/override alerts, create referrals, run visits | Read without consent, edit verified events |
| **Receiving Doctor** | Read the referral snapshot only, submit feedback | See beyond the snapshot, live timeline |
| **Emergency-enabled Doctor** | Break-glass access to the minimal emergency card | Full timeline, documents, search |
| **Pharmacist** (licence verified) | Prescription-bound access, safety check, record dispensing, ack/override alerts | See the timeline, edit prescriptions |
| **Verifier** (staff/CHW) | Capture and verify for a present, consenting patient, check patients in | Read timelines, grant consent for a patient |
| **Clinical Reviewer** | Draft/approve rules, thresholds, red-flag lists, emergency messages, review break-glass sessions | Access patient data |
| **Admin** | Users, credential approval, catalog import, audit export | Read clinical content |

**Authorization model:** RBAC (which endpoints a role may call) plus ABAC (per request: actor, patient, purpose, data categories, resource binding such as appointment, referral or prescription ID, consent state, appointment status, time window, device).

**Health ID:** `SID-` + 10 digits with a check digit. Random, unique, not derived from a phone number or national ID.

**Doctor and pharmacist verification:** register with BMDC number or pharmacy licence number plus a credential document, admin reviews (clinical reviewer may double-check), status `pending → verified → suspended`. An unverified doctor or pharmacist cannot create referrals or prescriptions, request consent, or dispense. Suspension revokes all active grants immediately.

---

## 3. System architecture

### 3.1 System context

```mermaid
flowchart LR
    P["Patient"] --> SYS
    D["Doctor / Receiving Doctor / Emergency Doctor"] --> SYS
    PH["Pharmacist"] --> SYS
    V["Verifier / CHW"] --> SYS
    CR["Clinical Reviewer"] --> SYS
    A["Admin"] --> SYS

    SYS[["SwasthyoID Platform"]]

    SYS --> SMS["SMS and Push gateway"]
    SYS --> AI["Cloud AI provider (only with patient opt-in)"]
    SYS --> CAT["Drug catalog source (licence checked)"]
    SYS --> OBJ["Encrypted object storage"]
```

### 3.2 Layered architecture

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        PA["Patient App"]
        DW["Doctor Web"]
        PW["Pharmacist Web"]
        VA["Verifier App"]
        AC["Admin and Reviewer Console"]
    end

    subgraph Gateway["API Gateway layer - /api/v1"]
        AUTH["JWT authentication"] --> RBAC["RBAC role check"]
        RBAC --> AZ["C1 authorize (ABAC)"]
        AZ --> AUD["C2 audit write"]
    end

    subgraph Core["Shared core services"]
        C1["C1 Consent and Authorization"]
        C2["C2 Audit"]
        C3["C3 Notification"]
        C4["C4 Event and Provenance"]
    end

    subgraph Modules["Feature modules"]
        M1["M1 Identity"]
        M2["M2 Capture and OCR"]
        M3["M3 Verification"]
        M4["M4 Timeline"]
        M5["M5 Summary and Search"]
        M6["M6 Safety Rules"]
        M7["M7 Triage"]
        M8["M8 Reminders"]
        M9["M9 Referral Passport"]
        M10["M10 Emergency Access"]
        M11["M11 e-Prescription and Pharmacist"]
        M12["M12 Appointment Consent"]
        M13["M13 Home Vitals"]
    end

    subgraph Infra["Infrastructure"]
        DB[("MongoDB")]
        VEC[("Qdrant")]
        OBJ[("Object storage")]
        Q[("Redis and Celery")]
        AIF["AI provider interface"]
    end

    Clients --> AUTH
    AUD --> Modules
    Modules --> Core
    Modules --> Infra
    Core --> Infra
```

**Architecture rules:** (1) every module uses C1 for access decisions; (2) every module writes to the timeline through C4 with provenance; (3) clients never touch the database; (4) a modular monolith until the pilot shows a reason to split.

### 3.3 Module dependency map

```mermaid
flowchart LR
    M1["M1 Identity"] --> C1["C1 Consent"]
    M2["M2 Capture"] --> M3["M3 Verification"]
    M3 --> C4["C4 Events"]
    C4 --> M4["M4 Timeline"]
    M4 --> M5["M5 Summary and Search"]
    M4 --> M6["M6 Safety Rules"]
    M4 --> M8["M8 Reminders"]
    M6 --> M11["M11 Prescription and Pharmacist"]
    M12["M12 Appointment Consent"] --> C1
    M9["M9 Referral"] --> C1
    M9 --> M4
    M10["M10 Emergency"] --> C1
    M11 --> C1
    M11 --> C4
    M13["M13 Home Vitals"] --> C4
    M13 --> M6
    M7["M7 Triage"] --> M6
    C1 --> C2["C2 Audit"]
    M1 --> C3["C3 Notification"]
    M8 --> C3
    M9 --> C3
    M10 --> C3
    M13 --> C3
```

### 3.4 Deployment view (prototype)

```mermaid
flowchart TB
    U["Clients (web and mobile)"] --> LB["TLS termination and reverse proxy"]
    LB --> APP["FastAPI application (modular monolith)"]
    APP --> MDB[("MongoDB - encrypted at rest")]
    APP --> QD[("Qdrant")]
    APP --> S3[("Object storage - encrypted")]
    APP --> RD[("Redis - broker and cache")]
    RD --> WK["Celery workers (OCR, extraction, summary, notifications)"]
    WK --> OCR["Local OCR engine"]
    WK --> MDB
    WK --> S3
    WK --> QD
    WK -. "opt-in only" .-> EXT["External AI provider"]
    BEAT["Celery beat (reminders, expiry sweeps, audit integrity job)"] --> RD
    WK --> GW["SMS and push gateway"]
```

### 3.5 Technology stack
FastAPI · MongoDB · Qdrant · Celery + Redis · encrypted object storage · local OCR (RapidOCR or Tesseract) · vision-language model behind an interface (opt-in only) · multilingual embedding model (Bangla + English). *(Open question: MongoDB + Qdrant versus one PostgreSQL with pgvector and pg_trgm.)*

---

## 4. Shared core services

### 4.1 C1 — Consent and Authorization

One service decides every non-patient access. It answers: who is asking, for which patient, for what purpose, which data categories, what did the patient allow, is it still active, has it expired or been revoked.

**Consent purposes**

| Purpose | Grantee | Bound to | Data scope | Activates when | Ends when |
|---|---|---|---|---|---|
| `TIMELINE` | Doctor | Doctor + patient | Categories patient picks (timeline, documents, safety) | Doctor submits patient OTP or QR | Expiry or revoke |
| `APPOINTMENT` | Doctor | Appointment ID | Categories patient approved at booking | Patient **checked in** | Visit completed, cancelled, grace period over, or max window |
| `REFERRAL` | Receiving doctor | Referral ID | Selected events in a frozen snapshot, not the live timeline | Patient approves | Token expiry, revoke, closed |
| `DISPENSING` | Pharmacist | Prescription ID | That prescription plus active medications and allergies for safety check | Patient shows QR or OTP | Dispense complete or expiry |
| `EMERGENCY` | Emergency-enabled doctor | Emergency session | Emergency card fields only | Break-glass with reason | Short time-boxed session |
| `CLOUD_AI` | System | Patient | Document image to external AI | Patient opts in | Patient opts out |

**Unified consent record:** `consent_id, patient_id, grantee_id, grantee_role, purpose, resource_binding {type,id}, allowed_categories[], method (OTP/QR/in-app), status, activated_at, expires_at, max_window_ends_at, revoked_at, revoked_by, consent_version, policy_version`.

**Consent state machine**

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> active : patient confirms and binding valid
    pending --> expired : never confirmed
    active --> expired : expiry or max window reached
    active --> revoked : patient revokes
    active --> suspended : grantee credential suspended
    suspended --> active : credential restored
    suspended --> revoked : patient revokes
    expired --> [*]
    revoked --> [*]
```

**Authorization decision flow**

```mermaid
flowchart TD
    S(["Access request"]) --> A1{"User verified and active?"}
    A1 -- no --> DENY["DENY and audit"]
    A1 -- yes --> A2{"Purpose is EMERGENCY?"}
    A2 -- yes --> EP["Emergency policy: capability, reason, time box"]
    EP -- fails --> DENY
    EP -- passes --> ALLOWE["ALLOW minimal card and audit first"]
    A2 -- no --> A3{"Consent found for grantee, patient, purpose?"}
    A3 -- no --> DENY
    A3 -- yes --> A4{"Status active and not expired or revoked?"}
    A4 -- no --> DENY
    A4 -- yes --> A5{"Resource binding valid? (appointment checked in, referral token live, prescription open)"}
    A5 -- no --> DENY
    A5 -- yes --> A6{"Requested categories subset of allowed?"}
    A6 -- no --> DENY
    A6 -- yes --> ALLOW["ALLOW with consent_id and audit"]
```

```python
def authorize_access(req, user, patient, consent):
    if not (user.is_verified and user.is_active):          return deny("user_not_verified")
    if req.purpose == "EMERGENCY":                         return emergency_policy(req, user, patient)
    if consent is None:                                    return deny("consent_required")
    if consent.patient_id != patient.id:                   return deny("patient_mismatch")
    if consent.grantee_id != user.id:                      return deny("grantee_mismatch")
    if consent.purpose != req.purpose:                     return deny("purpose_mismatch")
    if consent.status != "active":                         return deny("not_active")
    if now() > consent.expires_at or now() > consent.max_window_ends_at:
                                                           return deny("expired")
    if not binding_valid(consent, req.resource):           return deny("binding_invalid")
    if not req.data_categories.issubset(consent.allowed_categories):
                                                           return deny("category_not_allowed")
    return allow(consent_id=consent.id)                    # caller must write the C2 audit entry
```

Every deny is audited too. If C1 is down, all non-patient access stops (fail closed). Revocation applies from the next request.

### 4.2 C2 — Audit

| Requirement | Implementation |
|---|---|
| Append-only | No update or delete path in the application. The database user has insert permission only |
| Tamper-evident | Each entry stores `prev_hash` and `entry_hash`. A daily job verifies the chain. The chain head is anchored elsewhere |
| Server timestamps | Client time is never trusted |
| Actor context | actor_id, role, device_id, IP, user agent |
| Failed attempts | Every deny and auth failure is logged |
| Fail closed | If the audit write fails, the request fails. Emergency uses a write-ahead local buffer and reconciles later |
| Patient transparency | Patient sees who read what and when |

**Logged:** logins, consent create/activate/revoke/expire, every patient-data read, alert ack/override, rule approval, referral status changes (by whom), dispensing, break-glass, credential approval, threshold changes, notification failures.

```mermaid
flowchart LR
    E1["Entry n-1: hash H1"] --> E2["Entry n: prev_hash = H1, hash = H2"] --> E3["Entry n+1: prev_hash = H2, hash = H3"]
    E3 --> JOB["Daily integrity job recomputes chain"]
    JOB --> ANCH["Anchor chain head in separate store"]
```

### 4.3 C3 — Notification

```mermaid
sequenceDiagram
    autonumber
    participant SRC as Source module
    participant Q as Notification queue
    participant W as Worker
    participant PUSH as Push channel
    participant SMS as SMS channel
    participant APP as In-app inbox
    participant AUD as Audit

    SRC->>Q: enqueue event (persisted first)
    Q->>W: deliver
    W->>PUSH: send
    alt push fails
        W->>SMS: send
    end
    alt SMS fails
        W->>W: retry with backoff up to limit
        W->>APP: in-app fallback
        W->>AUD: log notification failure
    end
    W->>Q: record delivery status
```

Bangla by default, quiet hours in Asia/Dhaka (emergency-access alerts and critical safety messages ignore quiet hours). Templates for vitals and emergency are clinician-approved. Consent and emergency-access security notices cannot be switched off. The health event or audit record exists regardless of delivery.

### 4.4 C4 — Event and Provenance

**Mandatory fields on every event:** `event_id, event_type, patient_id, date + date_precision, actor_id, actor_role, source_type, source_document_id, recorded_at, verified_by, verified_at, verification_status, related_record_id, version, supersedes, payload`.

**Event types:** visit, diagnosis, medication, lab_result, allergy, follow_up, prescription, dispense, vital_reading, referral, referral_feedback.

| verification_status | Meaning | Example |
|---|---|---|
| `document_verified` | A human verified data extracted from paper | Verified prescription |
| `clinician_authored` | Authenticated doctor created it | e-Prescription |
| `pharmacist_recorded` | Authenticated pharmacist recorded it | Dispense event |
| `doctor_submitted` | Authenticated doctor submitted it (not clinically verified) | Referral feedback |
| `patient_reported` | Patient entered it | Home BP |
| `pending` | Awaiting verification | Not on the timeline |

**Rules:** events are never overwritten, a change is a new event linked by `supersedes`. Prescribed, dispensed and patient-taking are three separate events so the timeline shows which is current. Duplicates merge on `(type, date, generic, dose)`. Patient-reported events are never used as verified facts in safety rules and appear in their own summary section.

---

## 5. Modules

### M1 — Identity, Health ID and Consent Center
- Patient registration by phone OTP, profile (name, date of birth, sex, language), Health ID issue.
- Doctor, pharmacist and verifier onboarding with credential verification (section 2).
- Short-lived JWT access and refresh tokens, device binding.
- **Consent Center:** one list of every consent (who, purpose, categories, expiry), one-tap revoke, access history from the audit log, separate cloud-AI opt-in toggle, emergency profile settings.
- Doctor requests consent by Health ID, the patient confirms by OTP or QR.
- Edge cases: phone number change (re-verify, log out old devices), shared phone (app lock), minors and guardians (open question).
- **Done when:** a doctor without consent gets 403 and an audit entry exists; revoke blocks the next request; an unverified doctor cannot request consent.

```mermaid
sequenceDiagram
    autonumber
    actor Doc as Doctor
    participant API as API Gateway
    participant C1 as C1 Consent
    participant C3 as C3 Notification
    actor Pat as Patient
    participant C2 as C2 Audit

    Doc->>API: POST /consents/requests (Health ID, scope)
    API->>C1: create consent (pending)
    C1->>C3: send one-time code to patient
    C3-->>Pat: OTP or QR prompt
    Pat-->>Doc: tells code or shows QR
    Doc->>API: POST /consents/requests/id/confirm (code)
    API->>C1: verify code, set active, set expiry
    C1->>C2: audit consent granted
    C1-->>Doc: consent active
```

### M2 — Capture and Extraction
- Accept one or more JPEG/PNG images per document and a `doc_type` (prescription, lab report, discharge summary, other).
- Store the original encrypted. Document status `uploaded`.
- Background job: pre-process (rotate, deskew, denoise, contrast), local OCR, low-confidence regions to a vision-language model **only if the patient opted in**, otherwise left for manual entry.
- Parse to a typed schema with per-field confidence, validate types and dates, normalise Bangla and English numerals, fuzzy-match drug names to the catalog.
- Blur and glare detection asks for a retake.
- Retries with backoff, idempotent by `(document_id, version)`.
- **Done when:** every document ends in `needs_review` or `extraction_failed`; no extraction ever writes directly to events.

### M3 — Human Verification
- Image beside extracted fields. Fields under the confidence threshold (start 0.85, configurable) are highlighted. Confirm stays disabled until every field is edited or confirmed.
- Drug names resolve to generic ingredients through the catalog with suggestions.
- **Confirm:** one database transaction writes immutable events (`document_verified`), sets the document `verified`, logs each correction as before/after, and queues indexing and reminder proposals. **Reject:** status `rejected`.
- The verifier is the patient, or staff/CHW assisting a present, consenting patient.
- **Done when:** no event exists for an unverified document; per-field correction rate is recorded; repeating confirm creates no duplicates.

```mermaid
sequenceDiagram
    autonumber
    actor U as Patient or Verifier
    participant API as API Gateway
    participant M2 as M2 Capture
    participant W as Celery Worker
    participant OCR as Local OCR
    participant VLM as Cloud VLM (opt-in)
    participant M3 as M3 Verification
    participant C4 as C4 Event Store
    participant Q as Queue (index and reminders)

    U->>API: POST /documents with Idempotency-Key
    API->>M2: store encrypted image
    M2-->>U: status uploaded
    M2->>W: queue extraction
    W->>OCR: preprocess and OCR
    alt low confidence and cloud AI opt-in
        W->>VLM: low-confidence regions only
        VLM-->>W: values
    else no opt-in
        W->>W: mark fields for manual entry
    end
    W->>M2: save extraction, status needs_review
    U->>M3: review fields beside image
    U->>API: POST /documents/id/confirm
    API->>C4: write events in one transaction
    C4-->>U: verified, events on timeline
    C4->>Q: index job and reminder proposals
```

```mermaid
stateDiagram-v2
    [*] --> uploaded
    uploaded --> extracting
    extracting --> needs_review
    extracting --> extraction_failed
    extraction_failed --> extracting : re-queue
    extraction_failed --> needs_review : manual entry
    needs_review --> verified : confirm
    needs_review --> rejected : reject
    verified --> [*]
    rejected --> [*]
```

### M4 — Event Store and Timeline
- Events grouped by year and month, filters by type and date range, provenance badge on every event, link to the source image.
- Patient-reported events use a distinct label and filter. Correction history stays visible.
- Doctor view is restricted to the categories in the active consent.
- **Done when:** order is stable, history survives corrections, every event links to its source.

### M5 — Doctor Summary and Search
- **Sections:** active medications, allergies, documented diagnoses, recent labs with trend, recent visits, pending follow-ups, recent referral feedback, and patient-reported vitals (separate, labelled "reported by patient, not verified").
- An LLM writes the text from structured events only. Every sentence carries citations. A code validator checks each drug, number and date against the cited events. On failure or provider error, return a deterministic template summary (`mode: template`). Vitals appear only as template lines (values and dates), never interpreted.
- Cache by `(patient_id, events_version)`.
- **Search:** keyword and semantic, Bangla and English. `patient_id` and consent categories are hard filters in MongoDB and Qdrant. Results are event IDs with source links, not generated answers.
- **Done when:** a summary never contains an entity absent from cited events; a search never returns another patient's record or a category outside the consent.

```mermaid
sequenceDiagram
    autonumber
    actor Doc as Doctor
    participant API as API Gateway
    participant C1 as C1 Authorize
    participant M5 as M5 Summary
    participant C4 as C4 Events
    participant LLM as LLM provider
    participant VAL as Code validator
    participant C2 as C2 Audit

    Doc->>API: GET /patients/id/summary
    API->>C1: authorize (purpose, categories)
    C1-->>API: allow with consent_id
    API->>M5: build summary
    M5->>M5: cache hit for (patient, events_version)?
    alt cache miss
        M5->>C4: load permitted events
        M5->>LLM: events and prompt rules
        LLM-->>M5: text with citations
        M5->>VAL: check drugs, numbers, dates, cited IDs
        alt validation passes
            VAL-->>M5: ok
        else fails or provider error
            M5->>M5: build template summary
        end
    end
    M5->>C2: audit read
    M5-->>Doc: summary with citations
```

### M6 — Prescription Safety Rule Engine
- **Input:** drugs in a new or just-verified prescription plus the patient's active medications, allergies and documented diagnoses (verified, authored or pharmacist-recorded events only, never patient-reported).
- Normalise each brand to generic ingredients, then run the checks:

| Check | Rule source | Output |
|---|---|---|
| Drug-drug interaction | Pair table: contraindicated, major, moderate, minor | Alert with rule ID and explanation |
| Allergy | Allergy events, including ingredient class | Alert |
| Duplicate therapy | Same ingredient or class already active | Alert |
| Drug-disease | Drug and documented condition table | Alert |
| Recent same-class course | Configurable look-back | Review flag |
| Unrecognised drug | Not in catalog | `unrecognised` flag, never silently passed |

- Only rules with status `approved` run. Every change creates a new rule version.
- Each alert shows rule ID, severity, Bangla and English explanation, and links to the triggering events. The doctor or pharmacist must **acknowledge** or **override with a reason**, both audited.
- One rule registry holds all rule types: `ddi, allergy, duplicate, drug_disease, class_lookback, vital_threshold, red_flag, emergency_message`, with one approval workflow.
- Rule load error blocks the check with an explicit error.
- **Done when:** the same input always gives the same output and the clinician-written golden cases all pass.

### M7 — First-Aid and Department Guide (Triage)
- **Stage 1, red flags:** the clinician-approved list checks the first message and every answer. A match shows the emergency card (999) and stops the questions.
- **Stage 2, questions:** limited follow-ups chosen from a symptom-to-department guide table.
- **Stage 3, suggestion:** department with a short reason and a notice that this is guidance, not diagnosis. A classifier may add a second opinion. If it disagrees with a red-flag rule, the rule wins.
- First-aid cards are static and clinician-reviewed. An LLM may rephrase questions but never decides red flags or departments.
- If the rule engine is unavailable: show the emergency card and general advice to seek care.
- No free text kept after the session unless the patient saves it.
- **Done when:** every red-flag test case routes to the emergency card and no output states a diagnosis.

```mermaid
flowchart TD
    S(["Patient message"]) --> R1{"Red-flag rule match?"}
    R1 -- yes --> EC["Emergency card with 999 and stop questions"]
    R1 -- no --> Q1["Ask next question from guide table"]
    Q1 --> R2{"Answer matches red flag?"}
    R2 -- yes --> EC
    R2 -- no --> Q2{"Enough answers?"}
    Q2 -- no --> Q1
    Q2 -- yes --> DS["Suggest department with reason and guidance notice"]
    DS --> CL["Optional classifier second opinion"]
    CL --> R3{"Disagrees with red-flag rule?"}
    R3 -- yes --> EC
    R3 -- no --> DONE(["Show suggestion"])
    ENG["Rule engine down"] --> EC
```

### M8 — Reminders and Follow-up
- Proposals come only from verified events: medicine times from the written frequency and duration, follow-up visits, advised tests, refill nudges after a dispense event.
- **Nothing activates until the patient confirms.** Delivery by push and SMS in Bangla with quiet hours (Asia/Dhaka).
- Log taken, skipped, snoozed. If an advised test has no result in its window, send a nudge.
- Reminders repeat what the prescription says and never suggest a dose. A patient may create their own "measure BP" reminder, labelled as self-created.

```mermaid
stateDiagram-v2
    [*] --> proposed
    proposed --> active : patient confirms
    active --> paused : patient pauses
    paused --> active : patient resumes
    active --> ended : duration over or patient ends
    proposed --> ended : patient dismisses
    ended --> [*]
```

### M9 — Referral Passport
A verified, patient-controlled digital referral workflow, not a plain link.

```mermaid
sequenceDiagram
    autonumber
    actor RF as Referring Doctor
    participant M9 as M9 Referral
    participant C4 as C4 Events
    actor Pat as Patient
    participant C1 as C1 Consent
    actor RC as Receiving Doctor
    participant C3 as C3 Notification
    participant C2 as C2 Audit

    RF->>M9: create referral (reason, specialty, urgency, notes, selected events)
    M9->>C4: freeze verified events into snapshot
    M9->>C3: ask patient to approve
    C3-->>Pat: referral and shared data preview
    Pat->>M9: approve
    M9->>C1: create REFERRAL consent bound to referral and snapshot
    M9->>RC: deliver to verified account with time-limited token
    M9->>C2: audit status sent
    RC->>M9: open snapshot (status received, then seen)
    RC->>M9: submit feedback (authenticated)
    M9->>C4: write referral_feedback event (doctor_submitted)
    M9->>C3: notify referring doctor and patient
    RF->>M9: close referral
```

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> pending_patient_approval
    pending_patient_approval --> sent : patient approves
    pending_patient_approval --> declined : patient declines
    sent --> received
    received --> seen
    seen --> feedback_submitted
    feedback_submitted --> closed
    sent --> revoked : patient revokes
    received --> revoked
    seen --> revoked
    sent --> expired : token expires
    received --> expired
    seen --> expired
    declined --> [*]
    revoked --> [*]
    expired --> [*]
    closed --> [*]
```

| Component | Solution |
|---|---|
| Verification | Verified referring and receiving doctors |
| Referral ID | UUID |
| Snapshot | Timestamped, source-attributed, immutable |
| Consent | Referral-specific record, purpose `REFERRAL` |
| Access | RBAC + referral-specific ABAC bound to snapshot ID |
| Expiry | Configurable, plus patient revocation |
| Feedback | Authenticated doctor submission, author and timestamp verifiable. **Not automatically clinically verified** |
| Audit | Append-only, records who changed each status |
| Duplicates | Idempotency key |
| Offline (after pilot) | Encrypted PDF snapshot with QR verification, only if security policy allows |

**Urgent referral:** if the patient cannot approve in time, the referring doctor records the urgency reason, only the minimum categories are shared, the patient and emergency contact are notified immediately, the patient can revoke, and the case enters post-hoc review. Behind a feature flag until clinical and legal sign-off.

**Rules:** the receiving doctor sees only the snapshot. The snapshot date is always shown. New data needs a new consent request.

**Acceptance:** unverified doctors cannot refer; no clinical data is shared without approval (except the urgent workflow); only approved data is visible; expired or revoked access shows nothing; feedback author and timestamp are verifiable; every status change is audited; duplicate requests create one referral.

### M10 — Emergency Access (feature-flagged)
Minimal emergency card for an unconscious or incapable patient. Enabled only after clinical reviewer and legal approval.

- **Emergency profile:** the patient chooses fields (blood group if verified, allergies, active medications, long-term documented conditions, emergency contacts), built from verified events. Off until the patient turns it on.
- **Break-glass:** only emergency-enabled doctors. Reason and facility are mandatory. Session is time-boxed (default 2 hours, configurable) and shows card fields only.
- The audit entry is written first. The patient and emergency contact are notified immediately. Every session lands in post-hoc review. An unjustified access suspends the doctor's emergency capability.

```mermaid
sequenceDiagram
    autonumber
    actor ED as Emergency Doctor
    participant API as API Gateway
    participant C1 as C1 emergency policy
    participant C2 as C2 Audit
    participant M10 as M10 Emergency
    participant C3 as C3 Notification
    actor Pat as Patient and contact
    actor REV as Reviewer

    ED->>API: POST /emergency/access (Health ID or QR, reason, facility)
    API->>C1: verified, emergency-enabled, reason present?
    C1-->>API: allow
    API->>C2: write audit first (write-ahead)
    API->>M10: open time-boxed session
    M10-->>ED: minimal emergency card only
    M10->>C3: notify patient and emergency contact
    C3-->>Pat: emergency access alert
    M10->>M10: session auto-closes at time box
    M10->>REV: add to post-hoc review queue
    REV->>M10: mark justified or unjustified
```

```mermaid
stateDiagram-v2
    [*] --> active
    active --> closed : time box ends or doctor ends
    closed --> review_pending
    review_pending --> justified
    review_pending --> unjustified
    unjustified --> [*] : doctor capability suspended
    justified --> [*]
```

**Done when:** no break-glass access without a reason, every session notifies the patient, nothing beyond the card ever returns, all sessions reach review.

### M11 — e-Prescription and Pharmacist Dispensing
- **Doctor:** adds drugs from the catalog, M6 runs **before signing**, alerts acknowledged or overridden with reason, signing creates a `prescription` event (`clinician_authored`).
- **Pharmacist:** the patient presents a prescription QR or OTP (`DISPENSING` consent, bound to the prescription). The pharmacist sees only that prescription plus the active medications and allergies needed for the safety check. After the check, dispensing is recorded with items, quantity, substitution flag and date, creating a `dispense` event (`pharmacist_recorded`). Partial dispense and refills are separate events. The pharmacist cannot edit the prescription and can only query the doctor.
- Consent ends when dispensing completes. Prescribed, dispensed and patient-taking stay separate events.

```mermaid
sequenceDiagram
    autonumber
    actor Doc as Doctor
    participant M11 as M11 Prescribing
    participant M6 as M6 Safety Rules
    participant C4 as C4 Events
    actor Pat as Patient
    actor PH as Pharmacist
    participant C1 as C1 Consent
    participant C2 as C2 Audit

    Doc->>M11: draft prescription
    M11->>M6: safety check
    M6-->>Doc: alerts
    Doc->>M11: acknowledge or override with reason, sign
    M11->>C4: prescription event (clinician_authored)
    Pat->>PH: shows prescription QR or OTP
    PH->>C1: DISPENSING consent bound to prescription
    C1-->>PH: active
    PH->>M6: safety check with active meds and allergies
    M6-->>PH: alerts
    PH->>M11: acknowledge or override, record dispense
    M11->>C4: dispense event (pharmacist_recorded)
    M11->>C1: end consent on completion
    M11->>C2: audit dispense and reads
```

```mermaid
stateDiagram-v2
    [*] --> active : doctor signs
    active --> partially_dispensed
    partially_dispensed --> partially_dispensed : another partial
    partially_dispensed --> dispensed
    active --> dispensed
    active --> expired
    active --> cancelled
    partially_dispensed --> expired
    dispensed --> [*]
    expired --> [*]
    cancelled --> [*]
```

**Done when:** unverified pharmacists cannot dispense; dispensing needs a safety check (overrides carry a reason); consent ends at completion; the dispense event carries provenance.

### M12 — Appointment-Bound Explicit Consent
- Booking: patient picks a doctor and time, sees a **consent preview** of which categories the doctor could see, then gives a separate explicit approval. Booking works without consent, only clinical access is withheld.
- Access is tied to appointment ID + doctor ID + patient ID + categories.
- Clock time alone never decides expiry. **Appointment status plus a maximum access window** does:

| Appointment status | Access |
|---|---|
| `scheduled` | Pending (no access) |
| `checked_in` | Active, until the max window ends |
| `visit_completed` | Revoked |
| `no_show` | Expires after the configured grace period |
| `cancelled` | Revoked immediately |
| `rescheduled` | Old consent void, new consent required |

- Check-in is done by the patient (app or QR) or by a clinic verifier with the patient present. Multiple doctors are authorized individually. A follow-up appointment needs a new consent.

```mermaid
sequenceDiagram
    autonumber
    actor Pat as Patient
    participant M12 as M12 Appointments
    participant C1 as C1 Consent
    actor Doc as Doctor
    participant M5 as M5 Summary
    participant C2 as C2 Audit

    Pat->>M12: book appointment (doctor, time)
    M12-->>Pat: consent preview of categories
    Pat->>M12: explicit approval (separate confirmation)
    M12->>C1: create APPOINTMENT consent (pending)
    Pat->>M12: check in (app, QR, or verifier)
    M12->>C1: activate with max window
    Doc->>M5: open pre-visit summary
    M5->>C1: authorize
    C1-->>M5: allow
    M5->>C2: audit read
    Doc->>M12: complete visit
    M12->>C1: revoke consent
    M12-->>Pat: notify access ended
```

```mermaid
stateDiagram-v2
    [*] --> scheduled
    scheduled --> checked_in : check-in
    checked_in --> visit_completed : doctor completes
    scheduled --> no_show : grace period over
    scheduled --> cancelled
    checked_in --> cancelled
    scheduled --> rescheduled : new appointment and new consent
    visit_completed --> [*]
    no_show --> [*]
    cancelled --> [*]
    rescheduled --> [*]
```

**Done when:** no consent means no clinical access; the approved categories are visible to the patient; cancel and complete revoke access; a reschedule never inherits the old consent; every access is audited.

### M13 — Home Vitals (patient-reported BP and glucose)
MVP is **manual entry only**, no wearables.

- Entry captures value, unit (standardized dropdown), date and time, measurement context (glucose: fasting, post-meal, random; BP: home, resting), and source.
- Validation: unit, data type, plausibility. Suspicious values need confirmation.
- Creates a `vital_reading` event with `verification_status = patient_reported`. It can never be shown as device-verified.
- Rules: threshold rules live in the M6 registry. The default rules are drafted and approved by a clinical reviewer. A per-patient override can be set only by the treating doctor under active consent. Patients and verifiers cannot change thresholds. Every change is versioned and audited.
- Alerts are non-diagnostic. A critical-range reading (for example 180/120) must show a **clinically reviewed escalation message** telling the patient to seek appropriate urgent care, with a link to the emergency card. A normal reading never says "you are safe", only that it is within the configured range and to tell a doctor about symptoms.
- Correction: the original is preserved and a correction event is added. Duplicates are caught by event ID + timestamp.

```mermaid
sequenceDiagram
    autonumber
    actor Pat as Patient
    participant M13 as M13 Vitals
    participant VAL as Validator
    participant C4 as C4 Events
    participant M6 as M6 Threshold rules
    participant C3 as C3 Notification

    Pat->>M13: enter reading (value, unit, context, time)
    M13->>VAL: unit, type, plausibility
    alt suspicious value
        VAL-->>Pat: please confirm this reading
        Pat->>M13: confirm
    end
    M13->>C4: vital_reading event (patient_reported)
    M13->>M6: evaluate approved thresholds
    M6-->>M13: normal, flagged, or review required
    alt critical range
        M13->>C3: reviewed escalation message (ignores quiet hours)
    else flagged
        M13->>C3: non-diagnostic alert
    end
    M13-->>Pat: saved and labelled patient-reported
```

**Acceptance:** manual readings are never device-verified; unit validation is mandatory; glucose context is saved; only clinicians change thresholds; abnormal readings are flagged; alerts are never diagnoses; correcting a reading never loses the original.

---

## 6. Data model

### 6.1 Overview ERD (relationships only)

```mermaid
erDiagram
    CLINICS ||--o{ USERS : employs
    USERS ||--o{ CREDENTIALS : holds
    PATIENTS ||--o{ CONSENTS : grants
    USERS ||--o{ CONSENTS : "is grantee"
    CONSENTS ||--o{ CONSENT_EVENTS : logs
    PATIENTS ||--o| EMERGENCY_PROFILES : configures
    PATIENTS ||--o{ DOCUMENTS : uploads
    DOCUMENTS ||--o{ EXTRACTIONS : produces
    DOCUMENTS ||--o{ DOCUMENT_CORRECTIONS : records
    DOCUMENTS ||--o{ EVENTS : "is source of"
    PATIENTS ||--o{ EVENTS : owns
    EVENTS ||--o| EVENTS : supersedes
    PATIENTS ||--o{ SUMMARIES : caches
    PATIENTS ||--o{ APPOINTMENTS : books
    USERS ||--o{ APPOINTMENTS : attends
    APPOINTMENTS ||--o| CONSENTS : "scopes"
    PATIENTS ||--o{ PRESCRIPTIONS : receives
    USERS ||--o{ PRESCRIPTIONS : signs
    PRESCRIPTIONS ||--o{ PRESCRIPTION_ITEMS : contains
    PRESCRIPTION_ITEMS }o--|| DRUG_CATALOG : "maps to"
    PRESCRIPTIONS ||--o{ DISPENSE_RECORDS : "is dispensed by"
    USERS ||--o{ DISPENSE_RECORDS : records
    PRESCRIPTIONS ||--o{ SAFETY_ALERTS : triggers
    RULES ||--o{ SAFETY_ALERTS : "raised by"
    PATIENTS ||--o{ REFERRALS : "is subject of"
    REFERRALS ||--|| REFERRAL_SNAPSHOTS : freezes
    REFERRALS ||--o{ REFERRAL_EVENTS : tracks
    REFERRALS ||--o{ REFERRAL_FEEDBACK : receives
    PATIENTS ||--o{ VITAL_MEASUREMENTS : reports
    VITAL_MEASUREMENTS ||--o{ VITAL_ALERTS : raises
    VITAL_THRESHOLD_RULES ||--o{ VITAL_ALERTS : evaluates
    PATIENTS ||--o{ EMERGENCY_SESSIONS : "accessed in"
    USERS ||--o{ EMERGENCY_SESSIONS : opens
    PATIENTS ||--o{ REMINDERS : confirms
    REMINDERS ||--o{ ADHERENCE_LOGS : logs
    PATIENTS ||--o{ TRIAGE_SESSIONS : runs
    PATIENTS ||--o{ NOTIFICATIONS : receives
    NOTIFICATIONS ||--o{ NOTIFICATION_DELIVERIES : attempts
    USERS ||--o{ AUDIT_LOGS : performs
```

### 6.2 ERD A — Identity and consent

```mermaid
erDiagram
    CLINICS ||--o{ USERS : employs
    USERS ||--o{ CREDENTIALS : holds
    PATIENTS ||--o{ CONSENTS : grants
    USERS ||--o{ CONSENTS : "is grantee"
    CONSENTS ||--o{ CONSENT_EVENTS : logs
    PATIENTS ||--o| EMERGENCY_PROFILES : configures

    CLINICS {
        uuid id PK
        string name
        string district
    }
    PATIENTS {
        uuid id PK
        string health_id UK
        string phone_hash UK
        string phone_enc
        string name_enc
        date dob
        string sex
        string language
        boolean cloud_ai_opt_in
        datetime created_at
    }
    USERS {
        uuid id PK
        string role
        string name
        string status
        uuid clinic_id FK
        boolean emergency_enabled
    }
    CREDENTIALS {
        uuid id PK
        uuid user_id FK
        string type
        string number UK
        string doc_key
        string status
        uuid reviewed_by FK
    }
    CONSENTS {
        uuid id PK
        uuid patient_id FK
        uuid grantee_id FK
        string purpose
        string resource_type
        uuid resource_id
        string[] allowed_categories
        string method
        string status
        datetime activated_at
        datetime expires_at
        datetime max_window_ends_at
        datetime revoked_at
        int consent_version
    }
    CONSENT_EVENTS {
        uuid id PK
        uuid consent_id FK
        string action
        uuid actor_id
        datetime at
    }
    EMERGENCY_PROFILES {
        uuid id PK
        uuid patient_id FK
        boolean enabled
        string[] fields
        json contacts
    }
```

### 6.3 ERD B — Documents, events and timeline

```mermaid
erDiagram
    PATIENTS ||--o{ DOCUMENTS : uploads
    DOCUMENTS ||--o{ EXTRACTIONS : produces
    DOCUMENTS ||--o{ DOCUMENT_CORRECTIONS : records
    DOCUMENTS ||--o{ EVENTS : "is source of"
    PATIENTS ||--o{ EVENTS : owns
    USERS ||--o{ EVENTS : "acts on"
    EVENTS ||--o| EVENTS : supersedes
    PATIENTS ||--o{ SUMMARIES : caches

    DOCUMENTS {
        uuid id PK
        uuid patient_id FK
        string doc_type
        string[] image_keys
        string status
        uuid uploaded_by FK
        uuid verified_by FK
    }
    EXTRACTIONS {
        uuid id PK
        uuid document_id FK
        string engine
        json fields
        string raw_text
        int version
    }
    DOCUMENT_CORRECTIONS {
        uuid id PK
        uuid document_id FK
        string field
        string before_value
        string after_value
        uuid corrected_by FK
    }
    EVENTS {
        uuid id PK
        uuid patient_id FK
        string event_type
        date event_date
        string date_precision
        uuid actor_id FK
        string actor_role
        string source_type
        uuid source_document_id FK
        datetime recorded_at
        uuid verified_by FK
        datetime verified_at
        string verification_status
        uuid related_record_id
        int version
        uuid supersedes FK
        json payload
    }
    SUMMARIES {
        uuid id PK
        uuid patient_id FK
        int events_version
        string text
        json citations
        string mode
    }
```

### 6.4 ERD C — Clinical workflows

```mermaid
erDiagram
    PATIENTS ||--o{ APPOINTMENTS : books
    USERS ||--o{ APPOINTMENTS : attends
    PATIENTS ||--o{ PRESCRIPTIONS : receives
    USERS ||--o{ PRESCRIPTIONS : signs
    PRESCRIPTIONS ||--o{ PRESCRIPTION_ITEMS : contains
    PRESCRIPTION_ITEMS }o--|| DRUG_CATALOG : "maps to"
    PRESCRIPTIONS ||--o{ DISPENSE_RECORDS : "is dispensed by"
    USERS ||--o{ DISPENSE_RECORDS : records
    PRESCRIPTIONS ||--o{ SAFETY_ALERTS : triggers
    RULES ||--o{ SAFETY_ALERTS : "raised by"
    PATIENTS ||--o{ REFERRALS : "is subject of"
    REFERRALS ||--|| REFERRAL_SNAPSHOTS : freezes
    REFERRALS ||--o{ REFERRAL_EVENTS : tracks
    REFERRALS ||--o{ REFERRAL_FEEDBACK : receives
    PATIENTS ||--o{ VITAL_MEASUREMENTS : reports
    VITAL_MEASUREMENTS ||--o{ VITAL_ALERTS : raises
    VITAL_THRESHOLD_RULES ||--o{ VITAL_ALERTS : evaluates
    PATIENTS ||--o{ EMERGENCY_SESSIONS : "accessed in"
    USERS ||--o{ EMERGENCY_SESSIONS : opens
    PATIENTS ||--o{ REMINDERS : confirms
    REMINDERS ||--o{ ADHERENCE_LOGS : logs
    PATIENTS ||--o{ TRIAGE_SESSIONS : runs

    APPOINTMENTS {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        datetime slot
        string status
        datetime checked_in_at
        datetime completed_at
        uuid consent_id FK
    }
    PRESCRIPTIONS {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        string status
        datetime signed_at
        uuid event_id FK
    }
    PRESCRIPTION_ITEMS {
        uuid id PK
        uuid prescription_id FK
        uuid catalog_id FK
        string strength
        string frequency
        int duration_days
    }
    DISPENSE_RECORDS {
        uuid id PK
        uuid prescription_id FK
        uuid pharmacist_id FK
        json items
        boolean substituted
        datetime dispensed_at
        uuid event_id FK
    }
    SAFETY_ALERTS {
        uuid id PK
        uuid rule_id FK
        uuid prescription_id FK
        string severity
        uuid[] evidence_event_ids
        string ack_action
        string override_reason
        uuid ack_by FK
    }
    REFERRALS {
        uuid id PK
        uuid patient_id FK
        uuid from_doctor FK
        uuid to_doctor FK
        string reason
        string specialty
        string urgency
        string status
        datetime token_expires_at
        string idempotency_key UK
    }
    REFERRAL_SNAPSHOTS {
        uuid id PK
        uuid referral_id FK
        uuid[] event_refs
        json frozen_payload
        datetime created_at
    }
    REFERRAL_EVENTS {
        uuid id PK
        uuid referral_id FK
        string status_from
        string status_to
        uuid changed_by FK
        datetime at
    }
    REFERRAL_FEEDBACK {
        uuid id PK
        uuid referral_id FK
        uuid doctor_id FK
        string text
        datetime submitted_at
        uuid event_id FK
    }
    VITAL_MEASUREMENTS {
        uuid id PK
        uuid patient_id FK
        uuid event_id FK
        string vital_type
        string value
        string unit
        string context
        string source
        datetime recorded_at
    }
    VITAL_THRESHOLD_RULES {
        uuid id PK
        string vital_type
        uuid patient_id FK
        json thresholds
        int version
        uuid approved_by FK
    }
    VITAL_ALERTS {
        uuid id PK
        uuid measurement_id FK
        uuid rule_id FK
        string status
        datetime shown_at
    }
    EMERGENCY_SESSIONS {
        uuid id PK
        uuid doctor_id FK
        uuid patient_id FK
        string reason
        string facility
        datetime started_at
        datetime ended_at
        string review_status
    }
    REMINDERS {
        uuid id PK
        uuid patient_id FK
        uuid source_event_id FK
        json schedule
        string channel
        string status
        datetime confirmed_at
    }
    ADHERENCE_LOGS {
        uuid id PK
        uuid reminder_id FK
        datetime fired_at
        string response
    }
    TRIAGE_SESSIONS {
        uuid id PK
        uuid patient_id FK
        boolean red_flag
        string suggested_department
        datetime ended_at
    }
    DRUG_CATALOG {
        uuid id PK
        string brand
        string[] generics
        string strength
        string form
        string source
    }
    RULES {
        uuid id PK
        string rule_type
        json definition
        string severity
        string status
        uuid approved_by FK
        int version
    }
```

### 6.5 ERD D — Platform services

```mermaid
erDiagram
    USERS ||--o{ AUDIT_LOGS : performs
    PATIENTS ||--o{ AUDIT_LOGS : "is subject of"
    CONSENTS ||--o{ AUDIT_LOGS : "authorizes"
    PATIENTS ||--o{ NOTIFICATIONS : receives
    NOTIFICATIONS ||--o{ NOTIFICATION_DELIVERIES : attempts

    AUDIT_LOGS {
        uuid id PK
        datetime at
        uuid actor_id FK
        string actor_role
        string device_id
        string ip
        string action
        uuid patient_id FK
        string resource_type
        uuid resource_id
        uuid consent_id FK
        string purpose
        string result
        string reason
        string prev_hash
        string entry_hash
    }
    NOTIFICATIONS {
        uuid id PK
        uuid recipient_id FK
        string template_id
        json payload
        string status
    }
    NOTIFICATION_DELIVERIES {
        uuid id PK
        uuid notification_id FK
        string channel
        int attempt
        string status
        string error
        datetime at
    }
    IDEMPOTENCY_KEYS {
        string key PK
        string endpoint
        string result_ref
        datetime expires_at
    }
```

### 6.6 Storage notes
- **MongoDB:** all collections above. All records carry `created_at`, `updated_at`, IDs are UUIDs except the Health ID. Key indexes: `consents (grantee_id, patient_id, purpose, status)`, `events (patient_id, event_date)` and `(patient_id, event_type)`, `documents (patient_id, status)`, `reminders (status, next_fire_at)`. `events` and `audit_logs` are append-only.
- **Qdrant:** collection `event_chunks` with the vector, `patient_id` and `event_id` in the payload. `patient_id` is a payload index and is always sent as a filter.
- **Object storage:** `patients/{patient_id}/documents/{document_id}/{n}.jpg`, encrypted at rest.
- Phone and name are field-level encrypted. A phone hash is used for lookup.

---

## 7. API summary (`/api/v1`)

All endpoints need a bearer token except OTP request and verify. Errors use `{ "code": "consent_required", "message": "...", "details": {} }`. Every write accepts an `Idempotency-Key` header.

| Module | Endpoints | Role |
|---|---|---|
| M1 | `POST /auth/otp/request`, `/auth/otp/verify`, `/auth/refresh` | Any |
| M1 | `POST /credentials`, `POST /credentials/{id}/approve` | Doctor, pharmacist; admin |
| M1/C1 | `POST /consents/requests`, `POST /consents/requests/{id}/confirm` | Doctor |
| M1/C1 | `GET /consents`, `POST /consents/{id}/revoke`, `GET /me/access-history` | Patient |
| M2 | `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/extraction` | Patient, verifier |
| M3 | `PUT /documents/{id}/review`, `POST /documents/{id}/confirm`, `/reject` | Patient, verifier |
| M4 | `GET /patients/{id}/timeline?from&to&type` | Patient; doctor with consent |
| M5 | `GET /patients/{id}/summary`, `GET /patients/{id}/search?q=` | Doctor with consent |
| M6 | `POST /safety/check`, `POST /safety/alerts/{id}/ack` | Doctor, pharmacist |
| M7 | `POST /triage/sessions`, `POST /triage/sessions/{id}/answer` | Patient |
| M8 | `GET /reminders`, `PATCH /reminders/{id}`, `POST /reminders/{id}/log` | Patient |
| M9 | `POST /referrals`, `/referrals/{id}/approve`, `/decline`, `/revoke` | Doctor; patient |
| M9 | `GET /referrals/{id}`, `POST /referrals/{id}/received`, `/seen`, `/feedback`, `/close` | Receiving doctor; referrer |
| M10 | `PUT /me/emergency-profile`; `POST /emergency/access`; `GET /admin/emergency/reviews`, `POST .../{id}/review` | Patient; emergency doctor; reviewer |
| M11 | `POST /prescriptions`, `/prescriptions/{id}/sign`, `/prescriptions/{id}/dispense`; `POST /dispensing/requests`, `/confirm` | Doctor; pharmacist; patient |
| M12 | `POST /appointments`, `/appointments/{id}/consent`, `/checkin`, `/complete`, `/cancel`, `/reschedule`, `/no-show` | Patient, verifier, doctor |
| M13 | `POST /vitals`, `GET /vitals`, `POST /vitals/{id}/correct`, `PUT /patients/{id}/vital-thresholds` | Patient; treating doctor |
| Admin | `POST /rules`, `/rules/{id}/approve`, `POST /catalog/import`, `GET /audit` | Reviewer, admin |

**Async and idempotency:** Celery tasks are at-least-once, so each handler is keyed by `document_id` and `version` and does nothing on a repeat.

---

## 8. AI pipeline

AI is used in three places only: reading documents, writing summary text, and optionally rephrasing triage questions. Each sits behind a provider interface.

```mermaid
flowchart TD
    IMG["Document image"] --> PRE["Pre-process: rotate, deskew, denoise, contrast"]
    PRE --> OCR["Local OCR per page"]
    OCR --> CONF{"Region confidence below threshold?"}
    CONF -- no --> PARSE["Parse to schema, validate types and dates, normalise numerals"]
    CONF -- yes --> OPT{"Patient opted in to cloud AI?"}
    OPT -- yes --> VLM["Vision-language model on those regions"]
    OPT -- no --> MAN["Leave empty, mark for manual entry"]
    VLM --> PARSE
    MAN --> PARSE
    PARSE --> MATCH["Fuzzy match drugs to catalog, keep top suggestions"]
    MATCH --> OUT["Structured JSON with per-field confidence, status needs_review"]
```

```mermaid
flowchart LR
    EV["Permitted events from C4"] --> PR["Prompt rules: only supplied events, cite per sentence, no diagnosis or advice, fixed section order"]
    PR --> LLM["LLM text"]
    LLM --> V{"Validator: cited IDs exist and every drug, number, date is in cited events?"}
    V -- yes --> OK["Return LLM summary"]
    V -- no --> TPL["Deterministic template summary"]
    LLM -. "provider error" .-> TPL
```

**Retrieval:** chunk each event into short text with type and date, embed with a multilingual Bangla-English model, always filter by `patient_id` and consented categories, return event IDs.

**The AI never decides:** safety alerts, red flags, thresholds, emergency messages, department rules, dosing, or diagnosis.

**Pre-pilot evaluation gates**

| What | How | Gate |
|---|---|---|
| Extraction accuracy | Field-level on a labelled synthetic set of printed and handwritten prescriptions | Target agreed with the clinical reviewer |
| Summary faithfulness | Validator pass rate plus clinician reading of a sample | Zero unsupported statements in the sample |
| Safety rules | Reviewer-written golden cases | All pass |
| Red flags | Test set of emergency descriptions | All route to the emergency card |
| Vital thresholds | Reviewer-written golden cases | All pass, escalation always shown |
| Authorization | Purpose x state x role matrix | Every case allows or denies as expected |
| Audit integrity | Hash-chain verification | No break |

---

## 9. Non-functional requirements

| Area | Requirement |
|---|---|
| Legal | Design for explicit consent and breach reporting. The Personal Data Protection Ordinance 2025 treats health data as sensitive. Effective dates depend on gazette timing, so confirm status with a lawyer before the pilot |
| Consent | Explicit, scoped, time-limited, revocable. Separate cloud-AI opt-in. Consent wording is versioned |
| Encryption | TLS everywhere. Encryption at rest for database and object storage. Field-level encryption for phone and name |
| Access control | RBAC + ABAC on every request. No direct client database access |
| PII in logs | Application logs never contain names, phones or document text |
| Data minimisation | Store only schema fields. Referral and emergency share the minimum |
| Retention and deletion | Patient can export and delete data. Define the audit-log exception with a lawyer |
| Residency | Decide hosting location before the pilot (open question) |
| Performance targets | Timeline under 2 s, cached summary under 2 s, fresh summary under 10 s, extraction under 60 s per page, authorization check under 100 ms. Tune after measuring |
| Availability | Single region, daily backups, documented recovery steps |
| Offline (year 2) | Mobile offline capture and triage, offline referral PDF and emergency QR |
| Localisation | Bangla UI first, English second, Bangla numerals, Bangla and English OCR and search |
| Accessibility | Large text, simple flows for low literacy, voice input later |
| Observability | Structured logs, queue metrics, correction rate, summary validation failure rate, consent deny rate, notification failure rate, break-glass count |
| Testing | Unit tests for rules and validators, authorization matrix tests, end-to-end scenario, synthetic data only |

---

## 10. Edge cases and cross-module risks

| # | Case | Handling |
|---|---|---|
| 1 | Patient arrives late for an appointment | Status plus max window, not clock time |
| 2 | Check-in done but visit never completed | Max window auto-expires access |
| 3 | Reschedule, cancel, no-show | Old consent void, new consent needed, cancel revokes immediately, no-show expires after grace |
| 4 | Referral token expired or revoked | Request denied and audited |
| 5 | Same referral or dispense submitted twice | Idempotency key |
| 6 | Receiving doctor's credential suspended | All active grants suspended |
| 7 | New allergy verified after a prescription was signed | Re-run check and flag the prescription |
| 8 | Substitution, partial dispense, out of stock | Recorded as separate dispense events |
| 9 | Patient edits medication after dispensing | New patient-reported event, three events stay distinct |
| 10 | BP 180/120 entered | Reviewed escalation message is mandatory |
| 11 | Wrong unit or implausible value | Confirmation step, correction event |
| 12 | Break-glass notification fails | Retry, in-app fallback, failure audited |
| 13 | Audit store down | Fail closed (emergency buffer exception) |
| 14 | Rule registry fails to load | Safety check blocked with explicit error |
| 15 | No cloud-AI opt-in and low OCR confidence | Manual entry |
| 16 | Document confirmed twice | Idempotent, no duplicate events |
| 17 | Search returns a category outside the consent | Must never happen, covered by tests |
| 18 | Patient revokes just before a request | Next request is denied |
| 19 | Fake doctor or pharmacist | Credential verification, suspension revokes grants |
| 20 | Stale referral snapshot | Snapshot date always visible, new data needs new consent |

---

## 11. Roadmap (fixed)

**Assumptions:** a team of 3 to 4 engineers plus part-time clinical reviewer access. Start date Monday 16 November 2026. If the team size differs, keep the order and the exit gates, and rescale the durations. Each phase ends with a demo and an exit gate, and the next phase does not start until the gate passes.

```mermaid
gantt
    title SwasthyoID fixed roadmap
    dateFormat YYYY-MM-DD
    axisFormat %b %Y

    section Foundation
    P0 Decisions and skeleton            :p0, 2026-11-16, 14d
    P1 Core platform C1 to C4 and M1     :p1, after p0, 42d

    section Core clinical
    P2 Capture, verify, timeline         :p2, after p1, 56d
    P3 Summary, search, safety rules     :p3, after p2, 42d

    section Workflows
    P4 Appointment consent               :p4, after p3, 28d
    P5 Referral Passport                 :p5, after p4, 35d
    P6 Home Vitals                       :p6, after p5, 21d
    Prototype milestone                  :milestone, after p6, 0d
    P7 e-Prescription and Pharmacist     :p7, after p6, 35d
    P8 Triage and Reminders              :p8, after p7, 28d
    P9 Emergency Access (conditional)    :p9, after p8, 28d

    section Release
    P10 Hardening and evaluation         :p10, after p9, 42d
    Pilot                                :p11, after p10, 60d
```

| Phase | Dates | Scope | Deliverables | Exit gate |
|---|---|---|---|---|
| **P0 Decisions and skeleton** | 16 Nov – 29 Nov 2026 | Open questions 1, 2, 4, 5, 7 answered. Repo, CI, FastAPI skeleton, synthetic data generator. Clinical reviewer named | Decision log, running skeleton | All five decisions recorded |
| **P1 Core platform** | 30 Nov 2026 – 10 Jan 2027 | M1, C1, C2, C3, C4 skeleton, idempotency framework, authorization matrix test suite | Registration, Health ID, credentials, consent engine, hash-chained audit, event store with provenance, notification queue | Doctor without consent gets 403 plus audit entry. Revoke blocks the next request. Audit chain verifies |
| **P2 Capture, verify, timeline** | 11 Jan – 7 Mar 2027 | M2, M3, M4. In parallel, M6 core: catalog import, brand normalisation, rule loader, reviewer test cases | Photo to OCR to verified events to timeline on synthetic prescriptions | Every document ends in `needs_review` or `extraction_failed`. No unverified events. Correction rate recorded |
| **P3 Summary, search, safety** | 8 Mar – 18 Apr 2027 | M5, M6 wiring | Validated summary with template fallback, patient-filtered search, `/safety/check` on real events, ack and override | Summary has no unsupported entity. Golden safety cases all pass. Search leaks nothing |
| **P4 Appointment consent** | 19 Apr – 16 May 2027 | M12 | Booking, consent preview, check-in, status and window access, auto-expiry | Appointment status matrix passes. Reschedule never inherits consent |
| **P5 Referral Passport** | 17 May – 20 Jun 2027 | M9 | Snapshot, patient approval, token, status machine, authenticated feedback event, urgent workflow behind a flag | Referral acceptance criteria 1 to 7 pass |
| **P6 Home Vitals** | 21 Jun – 11 Jul 2027 | M13 | Manual entry, validation, reviewer-approved thresholds, escalation messages, summary section | Vitals acceptance criteria pass. Escalation always shown for critical range |
| **Prototype milestone** | 12 Jul 2027 | End-to-end scenario from section 1.4 on synthetic data | Demo | Scenario passes |
| **P7 e-Prescription and Pharmacist** | 12 Jul – 15 Aug 2027 | M11 | e-prescription signing with safety check, dispensing flow, pharmacist credentials | Unverified pharmacist blocked. Dispense needs a check. Consent ends on completion |
| **P8 Triage and Reminders** | 16 Aug – 12 Sep 2027 | M7, M8 | Red-flag triage, department guide, confirmed reminders, adherence log | Every red-flag case routes to emergency. No reminder without verified source and confirmation |
| **P9 Emergency Access (conditional)** | 13 Sep – 10 Oct 2027 | M10, **only if** the clinical reviewer and lawyer approve the policy; otherwise skipped and the time moves to P10 | Emergency profile, break-glass, notifications, post-hoc review | Reason mandatory, patient always notified, nothing beyond the card returns |
| **P10 Hardening and evaluation** | 11 Oct – 21 Nov 2027 | All modules | All evaluation gates in section 8, security review, clinical review, backup and recovery drill, legal review of consent wording and data protection status | Every gate passes |
| **Pilot** | 22 Nov 2027 – 20 Jan 2028 | Limited clinics and pharmacies, staff-assisted verification | Real-world metrics: correction rate, alert override rate, consent deny rate, notification failure rate | Pilot report with threshold tuning decisions |

**Prototype versus pilot scope**

| Tier | Includes |
|---|---|
| Prototype (by 12 Jul 2027) | C1–C4, M1–M6, M12, M9, M13 |
| Pilot | Everything above plus M7, M8, M11, and M10 if approved |
| Year 2 | Offline mobile, encrypted referral PDF with QR, offline emergency QR, automated credential checks, voice input, guardian flow. Wearables stay out of scope |

---

## 12. Open questions (decide by the phase shown)

| # | Question | Needed by |
|---|---|---|
| 1 | Which drug catalog source can we legally use, and on what terms? | P0 |
| 2 | MongoDB + Qdrant, or one PostgreSQL with pgvector and pg_trgm? | P0 |
| 3 | Who verifies in the pilot: patient only, or clinic staff too? | P2 |
| 4 | Where is the system hosted, and must health data stay in Bangladesh? | P0 |
| 5 | Which cloud AI provider and terms, or local-only? | P0 |
| 6 | Is emergency access in scope, and what is the break-glass policy? | P8 |
| 7 | Which clinician signs off rules, red flags, thresholds and emergency messages? | P0 |
| 8 | What does a lawyer say about the data protection law status and Bangla consent wording? | P1 |
| 9 | How do we verify BMDC and pharmacy licences beyond manual checking? | P5 |
| 10 | Appointment max access window and no-show grace period | P4 |
| 11 | Default referral token lifetime | P5 |
| 12 | Minors and guardian consent | P10 |
| 13 | Who sets vital plausibility and escalation ranges? | P6 |
| 14 | Is the emergency audit write-ahead buffer policy acceptable? | P9 |

**Related work note:** MedBangla AI (README review only) digitises single prescriptions and checks drug pairs. Cite it as related work and borrow ideas only (confidence-based OCR routing, trigram brand matching, a four-level severity scale). Its licence and catalog origin are unclear, so do not reuse its code or send real patient data to its API until the author confirms in writing.

---

## 13. Repository layout

```
swasthyoid/
├─ core/            # C1 consent_authz, C2 audit, C3 notification, C4 events_provenance
├─ identity/        # M1
├─ capture/         # M2
├─ verification/    # M3
├─ timeline/        # M4
├─ summary/         # M5
├─ safety/          # M6 and rule registry
├─ triage/          # M7
├─ reminders/       # M8
├─ referral/        # M9
├─ emergency/       # M10 (feature flag)
├─ prescribing/     # M11
├─ appointments/    # M12
├─ vitals/          # M13
├─ workers/         # Celery tasks
├─ api/             # routers and middleware (RBAC, then C1, then C2)
└─ tests/
   ├─ golden/       # clinician-written safety, red-flag, threshold cases
   ├─ authz_matrix/ # purpose x state x role
   └─ e2e/          # section 1.4 scenario
```

Only `core/` may implement consent, audit or notification logic. A CI lint enforces this.
