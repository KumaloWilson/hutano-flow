# Threat model and implemented controls

| Threat | Control | Regression evidence |
|---|---|---|
| Receptionist elevates urgency | Triage endpoint requires clinician or triage-nurse role | `test_receptionist_cannot_triage` |
| Queue token enumeration | 256-bit HMAC-derived secret, hash at rest, POST body rather than URL, throttling, generic 404 | `test_public_status_is_minimal`, rate-limit regression |
| Cross-facility access | Facility is derived from session; all object queries include it | `test_cross_facility_visit_is_hidden` |
| Sensitive SSE payload | Explicitly empty SSE data objects; role/facility-scoped invalidation references | `test_event_minimisation_and_research_role_boundary`, cursor/revocation test |
| Model input leaks into audit | Audit stores hashes and non-sensitive references only | `test_audit_has_no_observations` |
| Offline overwrite | no offline clinical mutation queue; row-version conflict is 409 | frontend + API tests |
| Unauthorised policy/capacity change | server-side role checks | `test_rbac_capacity` |
| Concurrent double call | facility transaction lock and conditional update; atomic audit/outbox/receipt | `test_real_postgres_concurrent_calls_and_append_only_audit` |
| CSRF/session theft | HttpOnly SameSite session, CSRF double-submit, expiry/revocation | `test_csrf_required` |
| Unsafe dataset | allow-listed MIME/size, direct-identifier rejection, local artifacts | research tests |

This is a prototype threat model, not an OWASP ASVS certification. TLS, encrypted backups, institutional access controls and an incident process are mandatory before any authorised non-synthetic evaluation.

## Local incident and access procedure

Stop using the demonstration if real information was entered accidentally. Restrict access, stop API/worker, preserve relevant audit and deployment information without publishing patient data, and notify the responsible research/institutional authority. Do not send raw data to external debugging or model services. Revoke affected accounts/sessions through administrator access controls; rotate deployment keys through environment configuration. Assess required notification and retention with the appropriate competent advisers before deleting evidence.

The administrator can redact expired synthetic pseudonyms using `/api/v1/admin/retention/redact` with its explicit confirmation phrase. This does not erase append-only audit evidence. Backups need an independently defined retention/access policy. Requests for individual records must be verified and handled through an authorised institution; the researcher role provides aggregate access only.

This implementation uses application-enforced facility scoping, not database row-level security. The runtime role is not a superuser and cannot perform schema changes or truncate tables. A database administrator remains trusted and can defeat database guards. Process-local limits, local HTTP cookies and public demo accounts must not be mistaken for a hardened public deployment. Compare against OWASP ASVS 5.0 and API Security Top 10 (2023) during an independent assessment; no certification is claimed.

