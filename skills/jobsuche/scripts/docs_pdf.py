#!/usr/bin/env python3
"""Convert .docx to PDF with whatever this computer has: Microsoft Word or LibreOffice.

  python 08_Scripts/docs_pdf.py check [--no-convert]   which engine works here (setup assistant)
  python 08_Scripts/docs_pdf.py convert file.docx      -> file.pdf next to it

documents.pdf_engine in 01_Config/settings.yaml: auto | word | libreoffice | none.
`auto` takes Word if it is installed (the layout then matches what the user sees in Word),
otherwise LibreOffice. Nothing here raises when no engine exists: to_pdf() returns None and the
caller prints the hint.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as cfg  # noqa: E402

HINT = ("Kein PDF-Programm gefunden. Bitte Microsoft Word oder LibreOffice (kostenlos, libreoffice.org) "
        "installieren oder die .docx-Datei selbst als PDF speichern.")
TIMEOUT = 180


def find_soffice():
    """LibreOffice binary from PATH or the usual install locations, else None."""
    for name in ("soffice", "libreoffice"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    home = Path.home()
    if sys.platform == "darwin":
        places = [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
                  home / "Applications/LibreOffice.app/Contents/MacOS/soffice"]
    elif sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA")]
        places = [Path(r) / sub / "program" / "soffice.exe" for r in roots if r
                  for sub in ("LibreOffice", "LibreOffice 7", "LibreOffice 24", "LibreOffice 25", "Programs/LibreOffice")]
    else:
        places = [Path(p) for p in ("/usr/bin/soffice", "/usr/local/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                                    "/usr/lib64/libreoffice/program/soffice", "/opt/libreoffice/program/soffice",
                                    "/snap/bin/libreoffice", "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice")]
        places += sorted(Path("/opt").glob("libreoffice*/program/soffice")) if Path("/opt").is_dir() else []
    return next((p for p in places if p.exists()), None)


def word_available():
    """True if Microsoft Word can be driven on this computer."""
    if sys.platform == "darwin":
        return any((base / "Microsoft Word.app").exists() for base in (Path("/Applications"), Path.home() / "Applications"))
    if sys.platform == "win32":
        try:
            import winreg
            import docx2pdf  # noqa: F401  (drives Word through COM)
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
            return True
        except Exception:
            return False
    return False


def engines():
    """Engines present here, in the order `auto` tries them."""
    found = []
    if word_available():
        found.append("word")
    if find_soffice():
        found.append("libreoffice")
    return found


def _osa_str(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _word_mac(src, pdf):
    """Word on the Mac only reads and writes without a "grant file access" dialog inside its own
    sandbox container, so the file is staged there and the PDF moved back."""
    container = Path.home() / "Library/Containers/com.microsoft.Word/Data"
    stage = (container / "tmp" / "jobsuche_pdf") if container.is_dir() else Path(tempfile.mkdtemp(prefix="jobsuche_pdf_"))
    stage.mkdir(parents=True, exist_ok=True)
    tmp_doc, tmp_pdf = stage / src.name, stage / pdf.name
    shutil.copyfile(src, tmp_doc)
    tmp_pdf.unlink(missing_ok=True)
    script = f'''tell application "Microsoft Word"
  set d to open file name (POSIX file "{_osa_str(tmp_doc)}" as string)
  save as d file name (POSIX file "{_osa_str(tmp_pdf)}" as string) file format format PDF
  close d saving no
end tell'''
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=TIMEOUT)
        if tmp_pdf.exists():
            shutil.move(str(tmp_pdf), pdf)
    finally:
        tmp_doc.unlink(missing_ok=True)
        tmp_pdf.unlink(missing_ok=True)


def _word_docx2pdf(src, pdf):
    """Word through the docx2pdf package (COM on Windows). Runs in a child process so its progress
    output and a hanging Word cannot disturb the caller."""
    code = "import sys; from docx2pdf import convert; convert(sys.argv[1], sys.argv[2])"
    subprocess.run([sys.executable, "-c", code, str(src), str(pdf)], check=True, capture_output=True, timeout=TIMEOUT)


def _libreoffice(src, pdf):
    soffice = find_soffice()
    with tempfile.TemporaryDirectory(prefix="jobsuche_lo_") as tmp:
        profile = Path(tmp, "profile").as_uri()      # own profile: works while LibreOffice is open
        subprocess.run([str(soffice), f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", tmp, str(src)], check=True, capture_output=True, timeout=TIMEOUT)
        made = Path(tmp) / (src.stem + ".pdf")
        if made.exists():
            shutil.move(str(made), pdf)


def _convert(engine, src, pdf):
    if engine == "libreoffice":
        _libreoffice(src, pdf)
    elif sys.platform == "darwin":
        try:
            _word_mac(src, pdf)
        except Exception:
            pdf.unlink(missing_ok=True)
        if not pdf.exists():                  # second way on the Mac, if the optional package is installed
            _word_docx2pdf(src, pdf)
    else:
        _word_docx2pdf(src, pdf)


def _order(engine=None):
    engine = (engine or cfg.load()["documents"]["pdf_engine"] or "auto").lower()
    if engine == "none":
        return []
    have = engines()
    return have if engine == "auto" else [e for e in have if e == engine]


def to_pdf(docx_path, out=None, engine=None):
    """PDF next to the .docx (or at `out`); None if no engine is configured, present or working."""
    src = Path(docx_path).resolve()
    pdf = Path(out).resolve() if out else src.with_suffix(".pdf")
    if not src.exists():
        return None
    for name in _order(engine):
        try:
            if pdf.exists():
                pdf.unlink()
            _convert(name, src, pdf)
            if pdf.exists() and pdf.stat().st_size > 0:
                return pdf
        except Exception:                     # missing rights, timeout, Word dialog: try the next engine
            continue
    return None


def pdf_pages(pdf_path):
    try:
        return len(re.findall(rb"/Type\s*/Page[^s]", Path(pdf_path).read_bytes())) or None
    except OSError:
        return None


def page_count(path, allow_word=False):
    """Pages of a PDF, or of a .docx converted in a temp folder. For a .docx only LibreOffice is
    used unless allow_word is set, so a mere check never opens Word on the user's screen."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return pdf_pages(path)
    order = [e for e in _order() if allow_word or e == "libreoffice"]
    if not order or not path.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="jobsuche_pages_") as tmp:
        for name in order:
            made = to_pdf(path, out=Path(tmp) / (path.stem + ".pdf"), engine=name)
            if made:
                return pdf_pages(made)
    return None


def check(convert=True):
    """What works on this computer; with convert=True each engine converts a small test file."""
    configured = cfg.load()["documents"]["pdf_engine"] or "auto"
    report = {"eingestellt": configured, "gefunden": engines(), "libreoffice_pfad": str(find_soffice() or ""),
              "funktioniert": [], "fehlgeschlagen": []}
    if convert and report["gefunden"]:
        try:
            import docx
            with tempfile.TemporaryDirectory(prefix="jobsuche_check_") as tmp:
                sample = Path(tmp) / "pdf_test.docx"
                d = docx.Document()
                d.add_paragraph("PDF-Test")
                d.save(str(sample))
                for name in report["gefunden"]:
                    made = to_pdf(sample, out=Path(tmp) / f"{name}.pdf", engine=name)
                    report["funktioniert" if made else "fehlgeschlagen"].append(name)
        except ImportError:
            report["hinweis"] = "python-docx fehlt – Testumwandlung übersprungen."
    usable = report["funktioniert"] if convert else report["gefunden"]
    order = [] if configured == "none" else [e for e in usable if configured in ("auto", e)]
    report["wird_genutzt"] = order[0] if order else None
    if not order:
        report["hinweis"] = ("PDF-Erzeugung ist abgeschaltet (documents.pdf_engine: none)." if configured == "none"
                             else HINT)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--no-convert", action="store_true", help="nur nachsehen, nichts umwandeln")
    v = sub.add_parser("convert")
    v.add_argument("docx")
    args = ap.parse_args()
    if args.cmd == "check":
        report = check(convert=not args.no_convert)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        sys.exit(0 if report["wird_genutzt"] else 1)
    pdf = to_pdf(args.docx)
    print(pdf if pdf else HINT)
    sys.exit(0 if pdf else 1)


if __name__ == "__main__":
    main()
