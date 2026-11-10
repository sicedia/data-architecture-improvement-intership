"""Design-time generation of the typed bronze tables and the RustWorker registry."""

from scrapagents.bronze.generator import (
    BronzeGenerationError,
    build_files,
    check_files,
    generate,
    write_files,
)

__all__ = ["BronzeGenerationError", "build_files", "check_files", "generate", "write_files"]
