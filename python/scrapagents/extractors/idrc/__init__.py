"""IDRC funding calls (idrc-crdi.ca): deterministic extractor, no LLM (invariant 1).

``records`` parses bytes into records, ``fetcher`` reads the site politely through the Obscura
router (invariant 3) and ``extractor`` streams the result to the Rust runtime (invariant 4).
"""
