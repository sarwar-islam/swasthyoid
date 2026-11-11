# SwasthyoID — working rules

- Spec is `docs/FRD.md`. Build one roadmap phase (section 11) at a time.
- Only `core/` may implement consent, audit or notification logic.
- Every non-patient read: RBAC -> C1 consent -> C2 audit.
- Events and audit entries are append-only.
- Safety rules, thresholds, red flags: deterministic code only, never an LLM.
- Safety paths fail closed. Synthetic data only.
- Do NOT invent clinical rules, drug interactions or thresholds; leave marked placeholders for the clinical reviewer.
