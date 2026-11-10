"""IDRC parser: RSS feed, HTML listing, detail pages (saved samples of the real site)."""

from __future__ import annotations

from pathlib import Path

import pytest
from scrapagents.extractors.idrc.records import (
    EMAIL_PLACEHOLDER,
    IdrcParseError,
    build_record,
    detect_block,
    parse_call_fields,
    parse_feed,
    parse_listing,
    redact_emails,
    slug_from_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "idrc"
JOHN = "idrc-invites-applications-john-g-bene-fellowship-2026"
INDIGENOUS = "connecting-indigenous-research-leadership-canada-and-global-south"
HUB = "womens-voice-and-leadership-learning-partnership-global-learning-hub"
NOW = "2026-11-09T12:00:00+00:00"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://idrc-crdi.ca/en/funding/some-call-2026", "some-call-2026"),
        ("/en/funding/some-call-2026/", "some-call-2026"),
        ("/en/funding", None),
        ("/en/funding/rss.xml", None),
        ("/en/funding/a/b", None),
        ("/en/idrc-invites-applications-john-g-bene-fellowship-2026", None),
        ("/fr/financement/appel", None),
    ],
)
def test_slug_from_url(value: str, expected: str | None) -> None:
    assert slug_from_url(value) == expected


def test_feed_items_carry_slug_node_id_and_publication_date() -> None:
    items = parse_feed(_read("feed.xml"))
    assert [item.slug for item in items] == [JOHN, INDIGENOUS]
    assert items[0].node_id == "147196"
    assert items[0].published_at == "2026-10-16T16:11:30+00:00"
    assert items[0].title.startswith("IDRC invites applications")


def test_feed_item_has_no_field_for_the_staff_email_of_dc_creator() -> None:
    for item in parse_feed(_read("feed.xml")):
        assert not hasattr(item, "creator")
        assert "creator" not in {name.lower() for name in vars(item)}


def test_invalid_feed_is_rejected() -> None:
    with pytest.raises(IdrcParseError):
        parse_feed(b"<html>not a feed</html>")
    with pytest.raises(IdrcParseError):
        parse_feed(b"<rss><nochannel/></rss>")


def test_listing_sections_and_row_fields() -> None:
    entries = parse_listing(_read("listing.html"))
    assert [(entry.slug, entry.section) for entry in entries] == [
        (JOHN, "open"),
        (INDIGENOUS, "closed"),
        (HUB, "closed"),
    ]
    assert entries[0].call_type == "Applications"
    assert entries[0].deadline == "2026-12-01T04:59:00+00:00"
    assert entries[0].url_path == f"/en/funding/{JOHN}"


def test_listing_without_calls_is_empty() -> None:
    assert parse_listing(b"<html><h2>Open calls</h2></html>") == []


def test_call_fields_from_an_rss_description() -> None:
    item = parse_feed(_read("feed.xml"))[0]
    fields = parse_call_fields(item.html)
    assert fields["status"] == "Open"
    assert fields["call_type"] == "Applications"
    assert fields["deadline"] == "2026-12-01T04:59:00+00:00"
    assert fields["program"] == "Climate-Resilient Food Systems"
    assert fields["topic"] == "Development; Environment; Food and Agriculture; Natural Resources"
    assert fields["budget"] == "Up to ten awards of a maximum of CA$30,000"
    assert fields["award_type"] == "Student award"
    assert fields["description_text"].startswith("Scope\n")


def test_call_fields_from_a_detail_page_match_the_same_parser() -> None:
    fields = parse_call_fields(_read("detail_listing_only.html"))
    assert fields["title"].startswith("Women")
    assert fields["status"] == "Closed"
    assert fields["duration"] == "48 months"
    assert fields["deadline"] == "2025-06-25T03:59:59+00:00"


def test_contact_email_is_never_read() -> None:
    for html in (parse_feed(_read("feed.xml"))[0].html, _read("detail_listing_only.html")):
        fields = parse_call_fields(html)
        assert "@" not in repr(fields)
        assert not any(key for key in fields if "contact" in key or "poc" in key)


def test_emails_in_the_call_text_are_redacted() -> None:
    html = (
        '<div class="field field--name-field-paragraphs"><p>Questions to '
        '<a href="mailto:jane.doe@idrc.ca">jane.doe@idrc.ca</a> '
        "or write to team@example.org.</p></div>"
    )
    text = parse_call_fields(html)["description_text"]
    assert "@" not in text
    assert text.count(EMAIL_PLACEHOLDER) == 2


def test_redact_emails() -> None:
    assert (
        redact_emails("a.b+c@x.co.uk and z@y.org") == f"{EMAIL_PLACEHOLDER} and {EMAIL_PLACEHOLDER}"
    )
    assert redact_emails("no email here") == "no email here"


def test_record_has_exactly_the_contract_columns() -> None:
    import yaml

    contract = yaml.safe_load(
        (Path(__file__).parents[2] / "configs/contracts/idrc/funding_opportunities.yml").read_text()
    )
    item = parse_feed(_read("feed.xml"))[0]
    built = build_record(
        slug=item.slug,
        source_url=item.url,
        fields={**parse_call_fields(item.html), "title": item.title},
        extraction_path="rss",
        retrieved_at=NOW,
        node_id=item.node_id,
        feed_published_at=item.published_at,
    )
    assert set(built.record) == {column["name"] for column in contract["columns"]}
    assert built.record["call_slug"] == item.slug
    assert built.findings == ()


def test_status_mismatch_between_listing_and_page_page_wins_and_is_a_finding() -> None:
    entry = parse_listing(_read("listing.html"))[0]  # listing says open
    fields = {**parse_call_fields(_read("detail_listing_only.html"))}  # page says Closed
    built = build_record(
        slug=entry.slug,
        source_url="https://idrc-crdi.ca/en/funding/x",
        fields=fields,
        extraction_path="html",
        retrieved_at=NOW,
        listing=entry,
    )
    assert built.record["status"] == "Closed"
    assert built.findings == (
        f"status_mismatch slug={entry.slug} listing=Open page=Closed extraction_path=html",
    )


def test_missing_values_fall_back_to_the_listing_row() -> None:
    entry = parse_listing(_read("listing.html"))[1]
    built = build_record(
        slug=entry.slug,
        source_url="u",
        fields={"title": None, "status": None},
        extraction_path="html",
        retrieved_at=NOW,
        listing=entry,
    )
    assert built.record["title"] == entry.title
    assert built.record["status"] == "Closed"
    assert built.record["call_type"] == entry.call_type
    assert built.record["deadline"] == entry.deadline


def test_record_without_title_or_status_is_rejected() -> None:
    with pytest.raises(IdrcParseError):
        build_record(slug="s", source_url="u", fields={}, extraction_path="html", retrieved_at=NOW)
    with pytest.raises(IdrcParseError):
        build_record(
            slug="s",
            source_url="u",
            fields={"title": "T"},
            extraction_path="html",
            retrieved_at=NOW,
        )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b"<div class='g-recaptcha'></div>", "captcha"),
        (403, b"", "waf"),
        (429, b"slow down", "waf"),
        (200, b"<title>Just a moment...</title>", "waf"),
        (200, b"<p>ok</p>", None),
    ],
)
def test_detect_block(status: int, body: bytes, expected: str | None) -> None:
    assert detect_block(status, body) == expected
