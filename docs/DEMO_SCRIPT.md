# Demonstration script

1. Start with `docker compose up --build` and open `http://localhost:3000`.
2. Sign in as `reception@demo.hutano.test` / `DemoReception1!`; create a synthetic patient and visit, then complete registration and copy the opaque status token.
3. Sign in as `clinician@demo.hutano.test` / `DemoClinician1!`; open Triage, assign P2 explicitly and confirm it.
4. Add two more patients with different confirmed priorities; inspect the Queue explanation and long-wait warnings.
5. Pin an eligible entry with a structured override reason. An administrator or researcher can inspect its privacy-safe Audit entry; a clinician does not receive unrestricted audit-log access.
6. Call, start and complete Consultation, route to Pharmacy, complete Pharmacy and close the visit.
7. Use the public Status page. Confirm it shows only token, general stage, number ahead and an estimate warning.
8. Set Consultation capacity to zero and observe the outage label without losing queued entries.
9. Open Analytics for stage wait mean/P90 and throughput.
10. Run a 300-patient fixed-seed simulation and export JSON/CSV.
11. Sign in as researcher and open AI research. Train the selected dataset and inspect its confusion matrix, reliability bins, baselines and limitations. It remains inactive. A clinician may record a synthetic-demonstration review in Help & safety; only an administrator may then activate/disable it. Review is not clinical approval. Keep it disabled for the manual-fallback demonstration.
12. Run `make test`, then the browser commands in README. Reset only disposable data with `make reset CONFIRM=RESET_SYNTHETIC_DEMO`, after any required backup.

Automated working screenshots are saved under `docs/evidence/`: the completed journey includes all four stages and the mobile token screenshot masks its secret. See `TEST_EVIDENCE.md` for actual pass counts, research results, acceptance mapping and limits.

