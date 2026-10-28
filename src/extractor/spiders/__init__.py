"""
Spider Registry & Factory
=========================
Gestiona la araña oficial especializada del proyecto IDCI y permite instanciarla
por su nombre de registro.
"""

from typing import Dict, Type, Optional
from .base_spider import BaseSpider
from .idci_spider import IDCISpider, IDRCSpider
from .cyted_spider import CytedSpider
from .worldbank_spider import WorldBankSpider
from .browser_helper import PlaywrightNavigator

SPIDER_REGISTRY: Dict[str, Type[BaseSpider]] = {
    "idci": IDCISpider,
    "idrc": IDRCSpider,
    "cyted": CytedSpider,
    "worldbank": WorldBankSpider,
    "world_bank": WorldBankSpider,
}


def get_spider(spider_name: Optional[str] = "idci", target_url: Optional[str] = None, institution_name: Optional[str] = None) -> BaseSpider:
    """Instancia y retorna el spider configurado a partir de su nombre registrado."""
    normalized_name = (spider_name or "idci").lower().strip()
    spider_cls = SPIDER_REGISTRY.get(normalized_name)
    if not spider_cls:
        available = ", ".join(SPIDER_REGISTRY.keys())
        raise ValueError(
            f"Spider '{spider_name}' no existe en el registro. Arañas disponibles: [{available}]"
        )
    return spider_cls(target_url=target_url, institution_name=institution_name)


def list_spiders() -> Dict[str, Dict[str, str]]:
    """Retorna información detallada de los spiders disponibles."""
    result = {}
    for key, cls in SPIDER_REGISTRY.items():
        result[key] = {
            "name": cls.name,
            "description": cls.description,
            "target_table": f"bronze.{cls.target_table}",
            "default_url": cls.default_url,
            "code_field": cls.code_field,
        }
    return result


__all__ = [
    "BaseSpider",
    "IDCISpider",
    "IDRCSpider",
    "CytedSpider",
    "WorldBankSpider",
    "PlaywrightNavigator",
    "get_spider",
    "list_spiders",
    "SPIDER_REGISTRY",
]
