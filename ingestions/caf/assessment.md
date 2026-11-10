# Assessment: caf

Phase 2. Written by `source-assessor`. Closed by **Gate H1** (human sign-off in `state.yml`).
Every `- Label:` line must be answered; `make status ID=caf` lists what is missing.

## Viability
- Legal / ToS risk: **Medium.** CAF (Banco de Desarrollo de América Latina y el Caribe) is a multilateral development institution. Procurement and consultancy notices are publicly published to ensure competitive bidding and transparency. The website terms of service (https://www.caf.com/es/terminos-y-condiciones/) reserve all copyrights. Automated extraction is not explicitly forbidden nor explicitly licensed, but access is governed by perimeter controls. The human must decide at Gate H1 if ingestion for analytical indexing under Producto OI is accepted as legitimate public information aggregation.
- Anti-bot risk and mitigation (obscura.sh): **High.** Probes conducted via Obscura (`obscura.sh` over CDP) revealed two technical obstacles: (1) Incomplete TLS certificate chain on `www.caf.com` (missing intermediate CA `Sectigo Public Server Authentication CA DV R36`), which was mitigated by injecting the intermediate CA into the Obscura container bundle; (2) Active Imperva / Incapsula WAF protecting the portal, returning HTTP 403 Forbidden (`blocked by: waf`) and JavaScript challenge scripts (`/_Incapsula_Resource`). Mitigation: Production extractor must navigate via `PlaywrightObscuraRouter` over CDP, configured with stealth headers and a single-slot Airflow Pool (`caf_web`) with inter-request delays (5-10 seconds) to avoid trigger thresholds. If Incapsula enforces hard interactive challenges, Gate H1 provides the human checkpoint to decide whether to continue or abort.
- Personal data (LOPDP): yes. Convocatorias and bidding documents (pliegos / TDRs) regularly list names, professional titles, and institutional contact emails of procurement officers, contact persons, or project supervisors. Under Ecuador's LOPDP, these are personal data. Mitigation: Flag contact fields as personal data in the contract schema; preserve them in Landing/Bronze for lineage, but exclude or pseudonymize them in Staging and Producto OI models.
- Duplicates an existing CEDIA source?: no. Verified against `configs/ingestions/` and `configs/contracts/`. CAF offers multilateral development tenders and technical assistance grants across Latin America that are not covered by existing sources (`idrc`, `ungm`).

## Refresh analysis
See `docs/implementation-plan.md` (every run reads the full scope).
- Full scope per run or incremental: **Full scope per run**, adhering to invariant PLAT-016 D1. Bronze manages deduplication via `persistence.mode: changes` keyed on `process_id` (or URL slug). The active catalogue contains approximately 30-80 concurrent opportunities, which can be scraped in a single batch without burdening the host.
- Proposed schedule and why: **Weekly (Mondays at 07:00 America/Guayaquil, `0 7 * * 1`)** or on-demand (`schedule: null`). CAF tenders have submission deadlines spanning several weeks; a weekly crawl captures new postings and status updates with minimal network impact.

## Payload triage preview
| Payload | Format | Goes to Tika? |
| :--- | :--- | :--- |
| Convocatorias portal listing `/es/trabaja-con-nosotros/convocatorias/` | html | no |
| Convocatoria detail page `/es/trabaja-con-nosotros/convocatorias/<slug>` | html | no |
| Términos de Referencia (TDR) / Pliego de bases | pdf | yes |

Format is one of json, xml, html, csv, pdf, docx. Only PDF and DOCX go to Apache Tika (answer `yes`);
JSON, XML, HTML and CSV never do (answer `no`). `scrapagents status` checks this.

## Recommendation
- Decision (go / no-go): go
- Reason: Conditional Go. The source provides high-value multilateral funding and consultancy opportunities for Latin America and Ecuador. Proceeding requires human sign-off on the Imperva WAF risk, the SSL intermediate configuration, and the LOPDP data handling strategy.
