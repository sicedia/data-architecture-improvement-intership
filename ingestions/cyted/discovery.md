# Discovery: cyted

Phase 1. Written by `source-scout`. Evidence only, no design decisions.
Every `- Label:` line must be answered; `make status ID=cyted` lists what is missing.

## Source
- Institution / portal URL: CYTED — Programa Iberoamericano de Ciencia y Tecnología para el Desarrollo (`https://www.cyted.org/`). Convocatorias documentation portal: `https://www.cyted.org/conteudo.php?idm=229` (Convocatoria Redes) and news/calls feed `https://www.cyted.org/noticias.php` (`conteudo.php?idnoticia=<id>`). Application submission portal is on a separate authenticated host (`https://portal.cyted.org/`, not probed).
- Access type (web): Public server-rendered PHP web portal (`<!--Current PHP version: 8.1.34-->`, developed by Ruralbit, charset `ISO-8859-15`). No public REST/JSON API or RSS feed was found. Probed through `scrapagents.stealth.PlaywrightObscuraRouter` connected to `obscura.sh` over CDP (`OBSCURA_CDP_URL`), with a 3-second polite delay between requests via `ingestions/cyted/probes/fetch_html.py`.
- robots.txt and Terms of Service: **robots.txt** (probed 2026-11-12, `https://www.cyted.org/robots.txt`): returns HTTP `404` (`<html><head></head><body></body></html>`), so no `Disallow` rules or `Crawl-delay` directives are published. **Terms of Service / Copyright** (read 2026-11-12 on `https://www.cyted.org/` and `https://www.cyted.org/conteudo.php?idm=230`): the site footer states `"2026 Copyright @ CYTED All Right Reserved | Desarrollado por: Ruralbit"` with institutional contact `Programa Iberoamericano de Ciencia y Tecnologia para el Desarrollo, Calle Amaniel nº4, 28015 - Madrid, e-mail: sgral@cyted.org`. No dedicated Terms of Use page or clause prohibiting automated indexing/archiving of public call announcements and downloadable bases/guidelines was found on `www.cyted.org`. Note: on `2026-03-17` (`conteudo.php?idnoticia=1621`), CYTED and CEDIA signed an international strategic alliance to promote scientific and technological cooperation.

## Probe evidence
Probes run through `scrapagents.stealth.PlaywrightObscuraRouter` (obscura.sh):
`make probe ID=cyted URL=<url>` appends the rows below.

| Date | URL | Status | Content type | Blocked by (captcha / waf / none) |
| :--- | :--- | :--- | :--- | :--- |
| 2026-11-12 | https://www.cyted.org/robots.txt | 404 | text/html | none |
| 2026-11-12 | https://www.cyted.org/ | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/conteudo.php?idm=229 | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/conteudo.php?idnoticia=1829 | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/noticias.php | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/conteudo.php?idm=230 | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/conteudo.php?idm=208 | 200 | text/html | none |
| 2026-11-12 | https://www.cyted.org/conteudo.php?idnoticia=1617 | 200 | text/html | none |

## Structure found
- Endpoints or DOM entry points: (1) Official Call Documentation page `GET https://www.cyted.org/conteudo.php?idm=229` (`div#conteudo.container.conteudo-rede`): left column (`div.col-md-5`) contains call summary text, open/close window (e.g., `"abierta a partir del 6 de Abril al 15 de mayo"`), contact email (`proyectos@cyted.org`) and phone (`+34 91 531 63 87`); right column (`div.col-md-7`) lists direct `<b><a href="assets/img/cyted/Convocatoria%202026/..."><label></a></b>` links to official PDF and DOCX documents in Spanish (`Castellano/`) and Portuguese (`Portugues/`). (2) Historical & Active Announcements listing `GET https://www.cyted.org/noticias.php`: renders all 283 news items on a single page (119 matching convocatoria/foros/redes/proyectos/becas), where each block has `<a href="conteudo.php?idnoticia=<id>"><h5><title></h5></a>`, `<h6>YYYY-MM-DD</h6>` (ISO date), and `<p class="news_desc">`. (3) Call Announcement Detail pages `GET https://www.cyted.org/conteudo.php?idnoticia=<id>` (e.g., `idnoticia=1829` `"CONVOCATORIA REDES TEMÁTICAS 2027"` published `2026-10-29` detailing the 7 thematic areas and 14 lines; `idnoticia=1617` `"CYTED abre la Convocatoria 2026..."` published `2026-03-13`; `idnoticia=1662` `"Cierre Convocatoria CYTED 2026"` published `2026-05-18`; `idnoticia=1043` `"Convocatoria a Foros CYTED 2025"`).
- Pagination and ordering: No pagination on either `conteudo.php?idm=229` or `noticias.php`. `noticias.php` serves all 283 historical records in a single ~351 KB HTML document ordered chronologically descending by publication date (`<h6>YYYY-MM-DD</h6>`, newest first, starting at `2026-10-29`).
- Authentication: None required for reading call announcements, thematic lines, or downloading official PDF/DOCX call bases and guidelines (`200 OK` to anonymous sessions). A login modal (`index.php?login`, Área de Gestión) and external link (`https://portal.cyted.org/`) exist solely for researchers submitting applications and managing active networks (out of scope).
- Payload formats: HTML (`text/html`, `ISO-8859-15` declared meta charset, ~30 KB per `conteudo.php` page, ~351 KB for `noticias.php`), PDF (`assets/img/cyted/Convocatoria%202026/.../*.pdf`, e.g., `01_Convocatoria_oficial_bases_y_lineas_2026_SP.pdf`, `02_Guia_del_solicitante_SP.pdf`, `04_Formulario_de_evaluacion_externa_SP.pdf`, `05_Preguntas_mas_frecuentes_Convocatoria_SP.pdf`, `06_Manual_para_la_presentacion_de_solicitudes_de_redes_(SP).pdf`), and DOCX (`03_memoria_tecnica_redes_tematicas_SP.docx`, `lista_entregables_SP.docx`, plus Portuguese equivalents). Under Invariant 4, only PDF and DOCX payloads go to Apache Tika.
- Estimated volume and change rate: Low volume and seasonal change rate. CYTED publishes 1 main annual call for Redes Temáticas (plus periodic calls for Foros Empresa-Academia, Proyectos Estratégicos, and Redes Eméritas — ~3 to 6 call-related announcements per year, with 14 downloadable PDF/DOCX documents on `idm=229` and ~119 historical call/program announcements across 283 total items in `noticias.php`).
