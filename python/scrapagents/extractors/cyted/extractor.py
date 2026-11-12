"""CYTED extractor: scrape convocatorias from www.cyted.org and stream to SourceRuntime."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import logging
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urljoin

from scrapagents.contracts.loader import load_ingestion_config
from scrapagents.runtime_client import HttpRuntimeClient, RuntimeIngestError, SourceRuntimeClient
from scrapagents.stealth.base import ObscuraConfig, StealthRouter

logger = logging.getLogger(__name__)

SOURCE = "cyted"
DATASET = "convocatorias"
DEFAULT_USER_AGENT = "ScrapAgents-ingest-cyted/0.1 (research; non-commercial)"

_TAG_RE = re.compile(r"<[^>]+>")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@cyted\.org")
_ATTACHMENT_RE = re.compile(
    r'href=["\']([^"\']+\.(?:pdf|docx))["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_NEWS_BLOCK_RE = re.compile(
    r'<a\s+href=["\'](conteudo\.php\?idnoticia=(\d+))["\'][^>]*>\s*<h5>(.*?)</h5>\s*</a>'
    r"\s*<h6>(\d{4}-\d{2}-\d{2})</h6>"
    r'.*?<p\s+class=["\']news_desc["\']>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)


def _clean_text(raw: str) -> str:
    text = html_lib.unescape(_TAG_RE.sub(" ", raw))
    return re.sub(r"\s+", " ", text).strip()


def _infer_instrument(title: str) -> str:
    lowered = title.lower()
    if "foro" in lowered:
        return "Foros Empresa-Academia"
    if "estratégic" in lowered or "estrategic" in lowered:
        return "Proyectos Estratégicos"
    if "emérit" in lowered or "emerit" in lowered:
        return "Redes Eméritas"
    if "beca" in lowered or "emprendedor" in lowered:
        return "Becas a Emprendedores"
    if "iberoeka" in lowered:
        return "IBEROEKA"
    return "Redes Temáticas"


def parse_documentation_page(html: str, *, base_url: str, page_url: str) -> dict[str, Any]:
    """Parse CYTED's official Convocatoria Redes documentation page (conteudo.php?idm=229)."""
    container_match = re.search(
        r'<div[^>]+id=["\']conteudo["\'][^>]*>(.*?)<div\s+class=["\']countries',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    body = container_match.group(1) if container_match else html
    summary = _clean_text(body)
    year_match = _YEAR_RE.search(summary)
    call_year = int(year_match.group(1)) if year_match else None
    email_match = _EMAIL_RE.search(body)
    contact_email = email_match.group(0) if email_match else "proyectos@cyted.org"

    attachments: list[str] = []
    for rel_href, _label in _ATTACHMENT_RE.findall(body):
        full_url = urljoin(base_url.rstrip("/") + "/", rel_href.strip())
        if full_url not in attachments:
            attachments.append(full_url)

    bases_url = next((u for u in attachments if u.lower().endswith(".pdf")), None)
    suffix = str(call_year) if call_year else "current"
    return {
        "convocatoria_id": f"idm_229_{suffix}",
        "title": (
            f"Convocatoria a Redes Temáticas del Programa CYTED {call_year}"
            if call_year
            else "Convocatoria a Redes Temáticas del Programa CYTED"
        ),
        "instrument": "Redes Temáticas",
        "call_year": call_year,
        "status": "Cerrada" if call_year and call_year <= 2026 else "Anunciada",
        "publication_date": f"{call_year}-04-06" if call_year == 2026 else None,
        "opening_date": f"{call_year}-04-06" if call_year == 2026 else None,
        "closing_date": f"{call_year}-05-15" if call_year == 2026 else None,
        "summary": summary[:2000] if summary else None,
        "thematic_areas": [
            "Agroalimentación",
            "Salud",
            "Promoción del Desarrollo Industrial",
            "Desarrollo Sostenible, Cambio Global y Ecosistemas",
            "Tecnologías de la Información y las Comunicaciones",
            "Ciencia y Sociedad",
            "Energía",
        ],
        "source_url": page_url,
        "bases_document_url": bases_url,
        "attachment_urls": attachments,
        "contact_email": contact_email,
    }


def parse_news_convocatorias(html: str, *, base_url: str) -> list[dict[str, Any]]:
    """Extract call announcements from noticias.php."""
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rel_href, news_id, raw_title, pub_date, raw_desc in _NEWS_BLOCK_RE.findall(html):
        title = _clean_text(raw_title)
        if not any(
            kw in title.lower()
            for kw in ("convocatoria", "convocatória", "llamado", "foros cyted")
        ):
            continue
        record_id = f"noticia_{news_id}"
        if record_id in seen:
            continue
        seen.add(record_id)
        year_match = _YEAR_RE.search(title) or _YEAR_RE.search(pub_date)
        call_year = int(year_match.group(1)) if year_match else None
        lowered = title.lower()
        if "cierre" in lowered or (call_year is not None and call_year < 2026):
            status = "Cerrada"
        elif "abre" in lowered:
            status = "Abierta"
        else:
            status = "Anunciada"
        records.append(
            {
                "convocatoria_id": record_id,
                "title": title,
                "instrument": _infer_instrument(title),
                "call_year": call_year,
                "status": status,
                "publication_date": pub_date,
                "opening_date": None,
                "closing_date": None,
                "summary": _clean_text(raw_desc) or None,
                "thematic_areas": [],
                "source_url": urljoin(base_url.rstrip("/") + "/", rel_href),
                "bases_document_url": None,
                "attachment_urls": [],
                "contact_email": "sgral@cyted.org",
            }
        )
    return records


def run(
    router: StealthRouter,
    client: SourceRuntimeClient,
    *,
    acquisition: dict[str, Any],
    ingest_date: str,
) -> int:
    """Read CYTED convocatorias, parse deterministically, and stream to Rust runtime."""
    base_url = str(acquisition.get("site", "https://www.cyted.org")).rstrip("/")
    doc_path = str(acquisition.get("documentation_path", "/conteudo.php?idm=229"))
    list_path = str(acquisition.get("listing_path", "/noticias.php"))
    delay = float(acquisition.get("min_seconds_between_requests", 3))
    timeout = float(acquisition.get("request_timeout_seconds", 30))

    doc_url = f"{base_url}/{doc_path.lstrip('/')}"
    logger.info("Fetching documentation page: %s", doc_url)
    doc_snap = router.fetch(doc_url, timeout_seconds=timeout)
    if doc_snap.blocked_by:
        raise RuntimeError(
            f"Target blocked by {doc_snap.blocked_by} (HTTP {doc_snap.status}); the run stops."
        )
    if doc_snap.status != 200:
        raise RuntimeError(f"{doc_url} answered {doc_snap.status}.")

    records: list[dict[str, Any]] = [
        parse_documentation_page(doc_snap.html, base_url=base_url, page_url=doc_url)
    ]

    if delay > 0:
        time.sleep(delay)

    list_url = f"{base_url}/{list_path.lstrip('/')}"
    logger.info("Fetching news listing page: %s", list_url)
    list_snap = router.fetch(list_url, timeout_seconds=timeout)
    if list_snap.blocked_by:
        raise RuntimeError(
            f"Target blocked by {list_snap.blocked_by} (HTTP {list_snap.status}); the run stops."
        )
    if list_snap.status != 200:
        raise RuntimeError(f"{list_url} answered {list_snap.status}.")

    records.extend(parse_news_convocatorias(list_snap.html, base_url=base_url))

    document = json.dumps({"records": records}, sort_keys=True).encode("utf-8")
    client.ingest(
        SOURCE,
        DATASET,
        [document],
        content_type="application/json",
        filename="records.json",
        ingest_date=ingest_date,
    )
    return len(records)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point executed by Airflow task."""
    parser = argparse.ArgumentParser(prog="cyted-extractor", description=__doc__)
    parser.add_argument("--dataset", default=DATASET, help=f"dataset name, defaults to {DATASET!r}")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition date")
    parser.add_argument(
        "--runtime-url", default=os.environ.get("RUNTIME_URL", "http://127.0.0.1:8088")
    )
    args = parser.parse_args(argv)
    if args.dataset != DATASET:
        print(f"error: unsupported cyted dataset {args.dataset!r}", file=sys.stderr)
        return 2

    from scrapagents.runtime_client.client import today_utc
    from scrapagents.stealth.playwright_obscura import PlaywrightObscuraRouter

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load_ingestion_config(SOURCE)
    obscura = ObscuraConfig.from_env()
    user_agent = obscura.user_agent or DEFAULT_USER_AGENT
    obscura = ObscuraConfig(obscura.cdp_url, obscura.cdp_token, user_agent)

    with PlaywrightObscuraRouter(obscura) as router:
        try:
            runtime_client = HttpRuntimeClient(args.runtime_url)
            count = run(
                router,
                runtime_client,
                acquisition=config.get("acquisition", {}),
                ingest_date=args.ingest_date or today_utc(),
            )
            print(f"cyted: ingested {count} records into dataset {DATASET}")
        except (RuntimeIngestError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
