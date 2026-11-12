# Assessment: cyted

Phase 2. Written by `source-assessor`. Closed by **Gate H1** (human sign-off in `state.yml`).
Every `- Label:` line must be answered; `make status ID=cyted` lists what is missing.

## Viability
- Legal / ToS risk: **Low to Medium.** Evidence (`discovery.md`, read 2026-11-12): `https://www.cyted.org/robots.txt` returns HTTP `404` (no `Disallow` rules or `Crawl-delay` published). The portal footer states `"2026 Copyright @ CYTED All Right Reserved | Desarrollado por: Ruralbit"` (`https://www.cyted.org/`), and no dedicated Terms of Use page or clause prohibiting automated indexing of public call announcements (`noticias.php`, `conteudo.php?idm=229`, `conteudo.php?idnoticia=<id>`) or downloadable call bases/guidelines (`assets/img/cyted/Convocatoria%202026/...`) exists. Furthermore, CYTED is a public intergovernmental Ibero-American program (in which Ecuador participates) and signed an international strategic alliance with CEDIA on `2026-03-17` (`conteudo.php?idnoticia=1621`). Every extracted record must preserve attribution (`CYTED`, source URL, and retrieval timestamp).
- Anti-bot risk and mitigation (obscura.sh): **Low, verified directly through Obscura over CDP.** All 7 probed URLs on `www.cyted.org` (`robots.txt` plus 6 PHP pages) answered `200 OK` (`404` for `robots.txt`) with `blocked_by: none` through `scrapagents.stealth.PlaywrightObscuraRouter` connected to `obscura.sh`. No WAF (Cloudflare, Imperva, Akamai), CAPTCHA, or JS challenge was observed; pages are server-rendered PHP (`ISO-8859-15`). Mitigation: (1) route all browser traffic through `PlaywrightObscuraRouter` (`OBSCURA_CDP_URL`); (2) enforce a **one-slot Airflow Pool** (`cyted_web`) and a polite delay (`>= 3 s`) between requests; (3) keep the authenticated management portal (`https://portal.cyted.org/`) strictly out of scope.
- Personal data (LOPDP): no. The target pages (`conteudo.php?idm=229` and call announcement pages `conteudo.php?idnoticia=<id>` such as `1829` and `1617`) contain only institutional contact channels (`proyectos@cyted.org`, `sgral@cyted.org`, `+34 91 531 63 87`), call dates, thematic lines, and official PDF/DOCX guidelines. Note: general news articles in `noticias.php` occasionally mention researchers or award recipients (e.g., `idnoticia=1240`), so the extractor must filter strictly to call/convocatoria announcements and official documentation, avoiding extraction of personal names or individual researcher emails.
- Duplicates an existing CEDIA source?: no. Checked `configs/ingestions/` (`caf`, `idrc`, `world_bank`), `configs/contracts/`, and `build/cedia_dags/` (`ces`, `eu_funding_tenders`, `idb`, `openalex`, `openerp`, `sia`, `simpler_grants`): no existing source ingests `cyted.org` or the Programa Iberoamericano de Ciencia y Tecnología para el Desarrollo (CYTED).
<!-- Personal data and Duplicates: start the answer with `yes` or `no`, then explain.
     Check configs/ingestions/ and configs/contracts/ for duplicates. -->

## Refresh analysis
See `docs/implementation-plan.md` (every run reads the full scope).
- Full scope per run or incremental: **Full scope on every run**, with table growth controlled in bronze via `persistence.mode: changes`. The total scope is small and unpaginated: 1 documentation page (`conteudo.php?idm=229` with 14 official PDF/DOCX call files), 1 news listing (`noticias.php`, ~351 KB containing all 283 historical items), and the subset of call announcement detail pages (`conteudo.php?idnoticia=<id>` matching convocatoria/redes/foros/proyectos/becas). Each run reads `conteudo.php?idm=229` and the call announcements from `noticias.php`, emitting normalized JSON records to `RustWorker` plus streaming the linked official PDF and DOCX call documents so `RustWorker` triages them through Apache Tika before landing in RustFS.
- Proposed schedule and why: **Weekly full read (`0 6 * * 1`, Monday 06:00 America/Guayaquil)** using a one-slot Airflow Pool (`cyted_web`). Why: CYTED opens one major annual call for Redes Temáticas (typically April–May, with thematic lines announced in October–December) plus 2–4 specific calls (Foros, Proyectos Estratégicos, Redes Eméritas) per year. A weekly schedule captures new calls and deadline updates promptly while placing negligible load on `www.cyted.org`.

## Payload triage preview
| Payload | Format | Goes to Tika? |
| :--- | :--- | :--- |
| Call documentation page `conteudo.php?idm=229` and call announcement pages `noticias.php` / `conteudo.php?idnoticia=<id>` | html | no |
| Normalized `convocatorias` dataset records emitted by the Python extractor to `RustWorker` | json | no |
| Official call bases, applicant guides, evaluation forms, FAQs, and manuals (`assets/img/cyted/Convocatoria%202026/.../*.pdf`) | pdf | yes |
| Official technical memory templates and deliverable checklists (`assets/img/cyted/Convocatoria%202026/.../*.docx`) | docx | yes |

Format is one of json, xml, html, csv, pdf, docx. Only PDF and DOCX go to Apache Tika (answer `yes`);
JSON, XML, HTML and CSV never do (answer `no`). `scrapagents status` checks this.

## Recommendation
- Decision (go / no-go): go
- Reason: Technical viability is verified end-to-end via Obscura (`200 OK`, no WAF/captcha, server-rendered HTML plus direct PDF/DOCX links), volume is small, legal risk is low (public intergovernmental program partnered with CEDIA), and there is no duplication with existing sources.
