#!/usr/bin/env python3
"""
Playwright Navigation & Binary Extractor Helper
=================================================
Módulo de navegación avanzada para el Scraper Efímero de IDCI.
- Abre Chromium en modo oculto (headless) con flags de optimización para contenedores.
- Implementa evasión de bloqueos JavaScript (anti-bot, spoofing de webdriver, plugins, WebGL).
- Resuelve renderizado dinámico en SPAs y frameworks modernos (React, Vue, Drupal, Angular).
- Detecta, intercepta y descarga archivos binarios asociados (PDFs, Word .docx/.doc, Excel, etc.).
- Permite uso como context manager o instancia persistente reutilizable durante el ciclo de vida del Spider.
"""

import os
import re
import time
import uuid
import hashlib
import logging
import mimetypes
from urllib.parse import urlparse, urljoin, unquote
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("browser_helper")

# Extensiones binarias soportadas para descarga
BINARY_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".rtf", ".zip", ".rar", ".7z", ".tar.gz", ".csv"
)

# Mapeo de extensiones a Content-Type estándar
MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".zip": "application/zip",
    ".csv": "text/csv",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Script JS inyectado en cada contexto para evadir detección de automatización
STEALTH_JS = """
// 1. Ocultar navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// 2. Simular window.chrome y sus APIs estándar
if (!window.chrome) {
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
}

// 3. Simular navigator.plugins con plugins típicos de Chromium
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ];
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (name) => plugins.find(p => p.name === name);
        plugins.refresh = () => {};
        return plugins;
    }
});

// 4. Idiomas del navegador
Object.defineProperty(navigator, 'languages', {
    get: () => ['es-ES', 'es', 'en-US', 'en']
});

// 5. Spoofing de WebGL para ocultar SwiftShader/headless
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL
    if (parameter === 37445) return 'Google Inc. (NVIDIA)';
    // UNMASKED_RENDERER_WEBGL
    if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return getParameter.apply(this, arguments);
};

// 6. Simular permisos de notificaciones
if (window.navigator && window.navigator.permissions) {
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
}
"""


class PlaywrightNavigator:
    """
    Ayudante de navegación con Playwright y Chromium headless.
    Controla el ciclo de vida del navegador, evasión de JavaScript y descarga de binarios.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        download_dir: Optional[str] = None,
        max_binaries_per_page: int = 10,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.download_dir = download_dir or "/tmp/idci_downloads"
        self.max_binaries_per_page = max_binaries_per_page

        os.makedirs(self.download_dir, exist_ok=True)

        self._playwright = None
        self._browser = None
        self._context = None
        self._is_active = False

    def is_binary_url(self, url: str) -> bool:
        """Determina si una URL apunta directamente a un archivo binario (PDF, Word, etc.)."""
        if not url:
            return False
        clean_path = url.split("?")[0].split("#")[0].lower()
        return any(clean_path.endswith(ext) for ext in BINARY_EXTENSIONS)

    def start(self) -> bool:
        """Inicializa Playwright y levanta Chromium en modo oculto (headless)."""
        if self._is_active:
            return True

        try:
            from playwright.sync_api import sync_playwright

            logger.info("Iniciando ayudante Playwright (Chromium Headless)...")
            self._playwright = sync_playwright().start()

            # Flags de Chromium adaptados para Docker y alta resiliencia
            chromium_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-position=0,0",
                "--ignore-certificate-errors",
                "--disable-extensions",
            ]

            self._browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=chromium_args,
            )

            # Contexto con resolución Full HD, locale y aceptación de descargas
            self._context = self._browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="es-ES",
                timezone_id="America/Bogota",
                ignore_https_errors=True,
                accept_downloads=True,
            )

            # Inyectar scripts anti-detección en cada nueva página
            self._context.add_init_script(STEALTH_JS)

            self._is_active = True
            logger.info("Chromium headless iniciado exitosamente con evasión de JavaScript activa.")
            return True

        except Exception as e:
            logger.warning(
                f"No se pudo iniciar Playwright/Chromium ({e}). Operará en modo fallback HTTP estándar."
            )
            self._is_active = False
            return False

    def close(self):
        """Libera de forma ordenada los recursos del navegador y Playwright."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.debug(f"Aviso al cerrar Playwright: {e}")
        finally:
            self._context = None
            self._browser = None
            self._playwright = None
            self._is_active = False
            logger.info("Sesión de Chromium headless finalizada.")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _auto_dismiss_banners(self, page):
        """Intenta cerrar o aceptar banners de cookies/privacidad comunes que bloquean contenido."""
        selectors = [
            "#onetrust-accept-btn-handler",
            "button[id*='cookie-accept']",
            "button[id*='accept-cookies']",
            "button:has-text('Aceptar')",
            "button:has-text('Aceptar todas')",
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Entendido')",
            ".agree-button",
            ".eu-cookie-compliance-secondary-button",
        ]
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                if locator.is_visible(timeout=800):
                    locator.click(timeout=800)
                    logger.debug(f"Banner interactivo cerrado con selector: {sel}")
                    break
            except Exception:
                continue

    def download_binary(
        self,
        url: str,
        referer: Optional[str] = None,
        custom_filename: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Descarga un archivo binario (PDF, Word, etc.) reutilizando las credenciales,
        cookies y headers de la sesión del navegador.
        Retorna los metadatos y el payload binario.
        """
        if not url:
            return None

        # Determinar nombre del archivo
        parsed = urlparse(url)
        path_name = unquote(os.path.basename(parsed.path))
        ext = os.path.splitext(path_name)[1].lower()

        if not ext and self.is_binary_url(url):
            for candidate_ext in BINARY_EXTENSIONS:
                if candidate_ext in url.lower():
                    ext = candidate_ext
                    break

        if not ext:
            ext = ".bin"

        clean_base = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", path_name) if path_name else "document"
        if not clean_base.endswith(ext):
            clean_base = f"{clean_base}{ext}"

        file_name = custom_filename or clean_base

        raw_bytes = None
        content_type = MIME_MAP.get(ext, "application/octet-stream")

        # 1. Intentar descarga mediante context.request (Playwright API Request)
        if self._is_active and self._context:
            try:
                headers = {"User-Agent": DEFAULT_USER_AGENT}
                if referer:
                    headers["Referer"] = referer

                resp = self._context.request.get(url, headers=headers, timeout=self.timeout_ms)
                if resp.status == 200:
                    raw_bytes = resp.body()
                    headers_dict = resp.headers
                    ct = headers_dict.get("content-type")
                    if ct:
                        content_type = ct.split(";")[0].strip()
            except Exception as e:
                logger.debug(f"Aviso al descargar binario con Playwright context.request ({url}): {e}")

        # 2. Fallback a requests / urllib si no se pudo con Playwright directamente
        if raw_bytes is None:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": referer or url},
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw_bytes = response.read(50 * 1024 * 1024)  # Límite 50 MB
                    ct = response.headers.get_content_type()
                    if ct:
                        content_type = ct
            except Exception as e:
                logger.warning(f"Error descargando archivo binario desde {url}: {e}")
                return None

        if not raw_bytes:
            return None

        file_size = len(raw_bytes)
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Guardar copia local en staging
        local_path = os.path.join(self.download_dir, f"{sha256_hash[:10]}_{file_name}")
        try:
            with open(local_path, "wb") as f:
                f.write(raw_bytes)
        except Exception as e:
            logger.debug(f"Aviso guardando archivo local: {e}")

        logger.info(
            f"📥 [Binario Descargado] {file_name} ({file_size / 1024:.1f} KB | {content_type}) -> {url}"
        )

        return {
            "file_name": file_name,
            "file_extension": ext,
            "content_type": content_type,
            "file_size_bytes": file_size,
            "sha256_hash": sha256_hash,
            "source_url": url,
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "local_path": local_path,
            "raw_bytes": raw_bytes,
        }

    def extract_binary_links(self, html: str, base_url: str) -> List[Dict[str, str]]:
        """
        Analiza el HTML y detecta enlaces `<a href="...">` que apuntan a archivos
        binarios (PDFs, Word, Excel, etc.).
        """
        if not html:
            return []

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        binary_links = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            abs_url = urljoin(base_url, href)
            clean_url = abs_url.split("?")[0].split("#")[0].lower()

            if any(clean_url.endswith(ext) for ext in BINARY_EXTENSIONS):
                if abs_url in seen:
                    continue
                seen.add(abs_url)

                anchor_text = a.get_text().strip()
                binary_links.append({
                    "url": abs_url,
                    "anchor_text": anchor_text or os.path.basename(clean_url),
                })

        return binary_links

    def navigate_and_extract(
        self,
        url: str,
        download_binaries: bool = True,
        max_binaries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Navega a una URL con Chromium headless, burla bloqueos de JavaScript,
        obtiene el DOM completamente hidratado y descarga archivos binarios adjuntos.
        """
        # Si la URL misma es un archivo binario directo:
        if self.is_binary_url(url):
            logger.info(f"La URL objetivo es un archivo binario directo: {url}")
            binary_meta = self.download_binary(url)
            bin_list = [binary_meta] if binary_meta else []
            fname = binary_meta.get("file_name", "document") if binary_meta else "document"
            return {
                "url": url,
                "title": fname,
                "html": "",
                "status_code": 200,
                "is_binary": True,
                "binaries": bin_list,
            }

        # Asegurar que Playwright esté iniciado
        if not self._is_active:
            self.start()

        # Si Playwright no está disponible, retornar indicador de fallo para fallback
        if not self._is_active or not self._context:
            return {"url": url, "html": "", "status_code": 0, "binaries": []}

        page = None
        max_bin_count = max_binaries or self.max_binaries_per_page
        downloaded_binaries = []

        try:
            page = self._context.new_page()

            # Navegar esperando que el DOM inicial cargue
            logger.info(f"Navegando con Chromium Headless a: {url}")
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )

            status_code = response.status if response else 200

            # Espera breve para permitir la ejecución de JavaScript y peticiones asíncronas
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass

            # Descartar banners o modales que bloquean el contenido
            self._auto_dismiss_banners(page)

            # Pequeño scroll para disparar eventos de lazy-loading
            try:
                page.evaluate("window.scrollBy(0, 400);")
                time.sleep(0.4)
            except Exception:
                pass

            # Extraer HTML completamente renderizado tras ejecución de JavaScript
            rendered_html = page.content()
            title = page.title()
            final_url = page.url

            logger.info(
                f"Página cargada exitosamente: '{title}' ({status_code}) [HTML: {len(rendered_html)} caracteres]"
            )

            # Detectar y descargar archivos binarios enlazados (PDFs, Word, etc.)
            if download_binaries:
                binary_links = self.extract_binary_links(rendered_html, final_url)
                if binary_links:
                    logger.info(
                        f"Archivos binarios descubiertos en la página: {len(binary_links)} (límite descarga: {max_bin_count})"
                    )
                    for item in binary_links[:max_bin_count]:
                        b_url = item["url"]
                        b_meta = self.download_binary(b_url, referer=final_url)
                        if b_meta:
                            b_meta["anchor_text"] = item.get("anchor_text", "")
                            downloaded_binaries.append(b_meta)

            return {
                "url": final_url,
                "title": title,
                "html": rendered_html,
                "status_code": status_code,
                "is_binary": False,
                "binaries": downloaded_binaries,
            }

        except Exception as e:
            logger.warning(f"Error en navegación Playwright para {url}: {e}")
            return {
                "url": url,
                "html": "",
                "status_code": 500,
                "error": str(e),
                "binaries": [],
            }
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
