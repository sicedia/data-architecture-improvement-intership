//! Binary triage: decide where a payload goes (architectural invariant 4).
//!
//! Only complex binary documents (PDF, DOCX and other Office files) reach Apache Tika.
//! Structured payloads (JSON, XML, HTML, CSV) bypass Tika. Anything unrecognised is
//! quarantined instead of guessed. Magic bytes win over the declared content type, so a
//! PDF served as `application/json` is still routed to Tika.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Structured {
    Json,
    Xml,
    Html,
    Csv,
}

impl Structured {
    pub fn as_str(self) -> &'static str {
        match self {
            Structured::Json => "json",
            Structured::Xml => "xml",
            Structured::Html => "html",
            Structured::Csv => "csv",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComplexBinary {
    Pdf,
    Docx,
    /// Other Office documents (xlsx, pptx, legacy OLE .doc/.xls).
    OtherOffice,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PayloadKind {
    Structured(Structured),
    ComplexBinary(ComplexBinary),
    Unknown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Route {
    /// Lightweight / structured data goes straight to PostgreSQL `bronze`.
    Bronze,
    /// Complex binary: forward to Apache Tika to extract plain text.
    Tika,
    /// Not recognised: keep the raw object and register it in quarantine.
    Quarantine,
}

/// What the extractor knows about the payload besides its bytes.
#[derive(Debug, Clone, Copy, Default)]
pub struct Hints<'a> {
    pub content_type: Option<&'a str>,
    pub filename: Option<&'a str>,
}

impl Hints<'_> {
    fn content_type_has(&self, needle: &str) -> bool {
        self.content_type
            .is_some_and(|ct| ct.to_ascii_lowercase().contains(needle))
    }

    fn extension_is(&self, ext: &str) -> bool {
        self.filename.is_some_and(|name| {
            name.rsplit_once('.')
                .is_some_and(|(_, e)| e.eq_ignore_ascii_case(ext))
        })
    }

    fn is(&self, ct_needle: &str, ext: &str) -> bool {
        self.content_type_has(ct_needle) || self.extension_is(ext)
    }
}

const PDF_MAGIC: &[u8] = b"%PDF-";
const ZIP_MAGIC: &[u8] = b"PK\x03\x04";
const OLE_MAGIC: &[u8] = &[0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1];
const UTF8_BOM: &[u8] = &[0xEF, 0xBB, 0xBF];
/// Bytes inspected: the caller passes the first chunk of the payload.
pub const SNIFF_LEN: usize = 1024;

/// Classify a payload from its first bytes (`head`) and the hints.
pub fn classify(head: &[u8], hints: &Hints) -> PayloadKind {
    let head = &head[..head.len().min(SNIFF_LEN)];

    if contains(head, PDF_MAGIC) {
        return PayloadKind::ComplexBinary(ComplexBinary::Pdf);
    }
    if head.starts_with(ZIP_MAGIC) {
        return classify_zip(hints);
    }
    if head.starts_with(OLE_MAGIC) {
        return PayloadKind::ComplexBinary(ComplexBinary::OtherOffice);
    }
    classify_text(head, hints)
}

/// A bare ZIP is only an Office document when a hint says so; otherwise it is unknown.
fn classify_zip(hints: &Hints) -> PayloadKind {
    if hints.is("wordprocessingml", "docx") {
        PayloadKind::ComplexBinary(ComplexBinary::Docx)
    } else if hints.is("spreadsheetml", "xlsx") || hints.is("presentationml", "pptx") {
        PayloadKind::ComplexBinary(ComplexBinary::OtherOffice)
    } else {
        PayloadKind::Unknown
    }
}

fn classify_text(head: &[u8], hints: &Hints) -> PayloadKind {
    let head = head.strip_prefix(UTF8_BOM).unwrap_or(head);
    if !is_text(head) {
        return PayloadKind::Unknown;
    }
    let text = String::from_utf8_lossy(head);
    let trimmed = text.trim_start();
    let lowered = trimmed.to_ascii_lowercase();

    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        return PayloadKind::Structured(Structured::Json);
    }
    if lowered.starts_with("<?xml") {
        return PayloadKind::Structured(Structured::Xml);
    }
    if lowered.starts_with("<!doctype html") || lowered.contains("<html") {
        return PayloadKind::Structured(Structured::Html);
    }
    if trimmed.starts_with('<') {
        return PayloadKind::Structured(if hints.content_type_has("html") {
            Structured::Html
        } else {
            Structured::Xml
        });
    }
    if hints.is("csv", "csv") {
        return PayloadKind::Structured(Structured::Csv);
    }
    PayloadKind::Unknown
}

/// Valid UTF-8 without NUL bytes. A multi-byte char cut at the end of `head` is accepted.
fn is_text(head: &[u8]) -> bool {
    if head.contains(&0) {
        return false;
    }
    match std::str::from_utf8(head) {
        Ok(_) => true,
        Err(e) => e.error_len().is_none(),
    }
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|w| w == needle)
}

/// Routing decision for a classified payload.
pub fn route(kind: PayloadKind) -> Route {
    match kind {
        PayloadKind::Structured(_) => Route::Bronze,
        PayloadKind::ComplexBinary(_) => Route::Tika,
        PayloadKind::Unknown => Route::Quarantine,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn none() -> Hints<'static> {
        Hints::default()
    }

    fn kind(head: &[u8], hints: Hints) -> PayloadKind {
        classify(head, &hints)
    }

    #[test]
    fn structured_payloads_bypass_tika() {
        for (bytes, expected) in [
            (&b"{\"a\":1}"[..], Structured::Json),
            (b"  [1,2]", Structured::Json),
            (b"<?xml version=\"1.0\"?><a/>", Structured::Xml),
            (b"<!DOCTYPE html><html></html>", Structured::Html),
            (b"\xEF\xBB\xBF{\"bom\":true}", Structured::Json),
        ] {
            let k = kind(bytes, none());
            assert_eq!(k, PayloadKind::Structured(expected));
            assert_eq!(route(k), Route::Bronze);
        }
    }

    #[test]
    fn csv_needs_a_hint() {
        let csv = b"id,name\n1,ana\n";
        assert_eq!(kind(csv, none()), PayloadKind::Unknown);
        let hinted = Hints {
            content_type: Some("text/csv; charset=utf-8"),
            filename: None,
        };
        assert_eq!(kind(csv, hinted), PayloadKind::Structured(Structured::Csv));
        let by_ext = Hints {
            content_type: None,
            filename: Some("data.CSV"),
        };
        assert_eq!(route(kind(csv, by_ext)), Route::Bronze);
    }

    #[test]
    fn pdf_and_office_documents_go_to_tika() {
        assert_eq!(route(kind(b"%PDF-1.7\n...", none())), Route::Tika);
        let docx = Hints {
            content_type: None,
            filename: Some("report.docx"),
        };
        assert_eq!(
            kind(b"PK\x03\x04rest", docx),
            PayloadKind::ComplexBinary(ComplexBinary::Docx)
        );
        let xlsx = Hints {
            content_type: Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            filename: None,
        };
        assert_eq!(route(kind(b"PK\x03\x04", xlsx)), Route::Tika);
        let ole = [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1, 0, 0];
        assert_eq!(route(kind(&ole, none())), Route::Tika);
    }

    #[test]
    fn magic_bytes_win_over_the_declared_content_type() {
        let lying = Hints {
            content_type: Some("application/json"),
            filename: Some("x.json"),
        };
        assert_eq!(route(kind(b"%PDF-1.4", lying)), Route::Tika);
    }

    #[test]
    fn bare_zip_and_unknown_binaries_are_quarantined() {
        assert_eq!(route(kind(b"PK\x03\x04", none())), Route::Quarantine);
        assert_eq!(
            route(kind(&[0x00, 0x01, 0x02, 0xFF], none())),
            Route::Quarantine
        );
        assert_eq!(route(kind(b"just some prose", none())), Route::Quarantine);
        assert_eq!(route(kind(b"", none())), Route::Quarantine);
    }

    #[test]
    fn a_multibyte_char_cut_at_the_sniff_boundary_is_still_text() {
        let mut data = b"{\"n\":\"".to_vec();
        data.extend_from_slice(&"é".as_bytes()[..1]);
        assert_eq!(
            kind(&data, none()),
            PayloadKind::Structured(Structured::Json)
        );
    }
}
