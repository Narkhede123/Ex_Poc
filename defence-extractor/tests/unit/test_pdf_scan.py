"""PDF challenge scan: file-level status, page flags from the text layer, duplicates in the summary."""

from defence_extractor.ingest.pdf_scan import scan_pdf, summarize


def _pdf(lines: list[str]) -> bytes:
    """A one-page PDF with Helvetica text lines (pdfium rebuilds the cross-reference table if it is off)."""
    ops = ["BT /F1 10 Tf 14 TL 60 780 Td"] + [f"({ln}) Tj T*" for ln in lines] + ["ET"]
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def test_contents_and_dot_leader_pages_are_flagged(tmp_path):
    lines = ["Contents"] + [f"STAR {i}0 ........................ {10 + i * 2}" for i in range(1, 7)]
    lines += ["Motor diameter, in ........................ 32.5", "Burn time, sec ........................ 53.6"]
    f = tmp_path / "catalogue.pdf"
    f.write_bytes(_pdf(lines))
    r = scan_pdf(f)
    assert r["status"] == "ok" and r["pages"] == 1
    assert {"dot_leaders", "contents_page"} <= set(r["page_flags"]["1"])
    assert "no_text" not in r["flags"]


def test_a_file_that_is_not_a_pdf_and_duplicates_are_reported(tmp_path):
    bad = tmp_path / "error.pdf"
    bad.write_bytes(b"<html><body>404 Not Found</body></html>")
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_pdf(["Range 120 km"]))
    b.write_bytes(_pdf(["Range 120 km"]))
    res = [scan_pdf(bad), scan_pdf(a), scan_pdf(b)]
    assert res[0]["status"] == "not_pdf"
    sm = summarize(res)
    rows = {r["flag"]: r for r in sm["flags"]}
    assert rows["not_pdf"]["files"] == 1 and rows["duplicate_file"]["files"] == 1


def _pdf_runs(runs: list[tuple[str, float, float, float, bool]], size=(595, 842)) -> bytes:
    """A one-page PDF from text runs (text, x, y, font size, rotated 90 degrees)."""
    ops = []
    for text, x, y, fs, rot in runs:
        m = f"0 1 -1 0 {x} {y}" if rot else f"1 0 0 1 {x} {y}"
        ops.append(f"BT /F1 {fs} Tf {m} Tm ({text}) Tj ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>" % size,
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def _flags(tmp_path, runs, size=(595, 842)) -> set[str]:
    f = tmp_path / "t.pdf"
    f.write_bytes(_pdf_runs(runs, size))
    return set(scan_pdf(f)["page_flags"].get("1", []))


def test_rotated_tiny_marked_and_two_column_pages_are_flagged(tmp_path):
    body = [(f"Line {i} of the vehicle description with several words", 60, 780 - 14 * i, 10, False) for i in range(30)]
    assert "rotated_text" not in _flags(tmp_path, body)
    side = [(f"Rotated label number {i}", 40 + 12 * i, 100, 10, True) for i in range(20)]
    assert "rotated_text" in _flags(tmp_path, body[:10] + side)
    tiny = [(f"Note {i}: footnote text in small type", 60, 300 - 6 * i, 4, False) for i in range(40)]
    assert "tiny_text" in _flags(tmp_path, body[:10] + tiny)
    assert "classification_marking" in _flags(tmp_path, body + [("NATO UNCLASSIFIED", 250, 820, 10, False)])
    cols = [(f"Left column line {i} text", 50, 780 - 14 * i, 10, False) for i in range(25)]
    cols += [(f"Right column line {i} text", 320, 780 - 14 * i, 10, False) for i in range(25)]
    assert "multi_column" in _flags(tmp_path, cols)
    assert "oversized_page" in _flags(tmp_path, body, size=(1684, 2384))  # A1 poster
