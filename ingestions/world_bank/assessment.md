# Assessment: world_bank

Phase 2. Written by `source-assessor`. Closed by **Gate H1** (human sign-off in `state.yml`).
Every `- Label:` line must be answered; `make status ID=world_bank` lists what is missing.

## Viability
- Legal / ToS risk: **Low.** The World Bank Group publishes procurement notices for public transparency and international competitive bidding, and licenses its datasets under the **Creative Commons Attribution 4.0 International License (CC BY 4.0)** (`https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets`, read 2026-11-11), which explicitly permits copying, extracting, downloading, adapting, and redistributing data with attribution ("The World Bank: Procurement Notices"). `https://projects.worldbank.org/robots.txt` sets `Allow: *` and does not disallow `/en/projects-operations/procurement`.
- Anti-bot risk and mitigation (obscura.sh): **Low.** Probes executed via `scrapagents.stealth.PlaywrightObscuraRouter` (`obscura.sh` over CDP) against both `https://projects.worldbank.org/en/projects-operations/procurement?srce=both` and `https://search.worldbank.org/api/v2/procnotices?format=json` returned HTTP 200 with `blocked_by: none` (no WAF or CAPTCHA challenges). Mitigation: Production extraction uses `PlaywrightObscuraRouter` over CDP (`OBSCURA_CDP_URL`) combined with a single-slot Airflow Pool (`world_bank_web`) and polite request pacing to avoid rate-limiting.
- Personal data (LOPDP): yes. Procurement notices include `contact_name`, `contact_email`, `contact_phone_no`, and `contact_address` identifying procurement officers or project coordinators at borrowing agencies. Under Ecuador's LOPDP, these constitute personal data of natural persons acting in an institutional capacity. Mitigation: Mark `personal_data: true` in the dataset contract, preserve raw payloads in Landing/Bronze for lineage, and strip or mask individual contact PII when projecting into Producto OI analytical models.
- Duplicates an existing CEDIA source?: no. Verified against `configs/ingestions/` (`caf.yml`, `idrc.yml`) and `configs/contracts/` (`caf`, `idrc`). Neither World Bank (`projects.worldbank.org` / `search.worldbank.org`) nor its procurement notices dataset is currently ingested.

## Refresh analysis
See `docs/implementation-plan.md` (every run reads the full scope).
- Full scope per run or incremental: **Full scope per run** of the configured active/recent procurement notice window, in accordance with platform invariant PLAT-016 D1. Deduplication and change capture are enforced in Bronze via `persistence.mode: changes` keyed on the World Bank notice ID (`id`, e.g., `OP00480372`).
- Proposed schedule and why: **Daily at 06:00 America/Guayaquil (`0 6 * * *`)** (or `schedule: null` for manual trigger during initial verification). New Requests for Expressions of Interest (REOI) and Invitation for Bids (IFB) are published daily across borrowing member countries, making a daily cadence optimal for timely opportunity discovery.

## Payload triage preview
| Payload | Format | Goes to Tika? |
| :--- | :--- | :--- |
| Procurement portal listing and detail pages (`/en/projects-operations/procurement`) | html | no |
| Procurement notices structured feed (`/api/v2/procnotices?format=json`) | json | no |
| Attached bidding documents / Terms of Reference (when linked) | pdf | yes |

Format is one of json, xml, html, csv, pdf, docx. Only PDF and DOCX go to Apache Tika (answer `yes`);
JSON, XML, HTML and CSV never do (answer `no`). `scrapagents status` checks this.

## Recommendation
- Decision (go / no-go): go
- Reason: High-value multilateral procurement source with explicit open data licensing (CC BY 4.0), permissive `robots.txt`, clean unblocked JSON/HTML access (`blocked_by: none`), and straightforward LOPDP governance via `personal_data: true` contract tagging.
