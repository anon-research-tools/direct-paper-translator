#!/usr/bin/env python3
"""Three-step direct PDF translation helper: prepare text, then render Markdown."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
TEMPLATE = SKILL_DIR / "assets" / "paper.html"


class FlowError(RuntimeError):
    pass


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _write_json(path: Path, value: dict) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _wrap_long_line(line: str, limit: int = 1200) -> list[str]:
    parts = []
    remaining = line
    while len(remaining) > limit:
        window = remaining[:limit]
        candidates = [
            window.rfind(mark, limit // 2)
            for mark in ("。", "！", "？", ". ", "; ", "；", "，", ", ", " ")
        ]
        cut = max(candidates)
        if cut < limit // 2:
            cut = limit
        elif window[cut:cut + 2] in {". ", "; ", ", "}:
            cut += 1
        else:
            cut += 1
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts or [""]


def _normalize_page(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    blank = False
    for raw in text.splitlines():
        value = raw.rstrip()
        if not value.strip():
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.extend(_wrap_long_line(value))
    return "\n".join(lines).strip()


def prepare(pdf: Path, jobs_root: Path) -> dict:
    try:
        import fitz
    except ImportError as exc:
        raise FlowError("缺少 PyMuPDF（fitz），无法读取 PDF 文字层") from exc

    pdf = pdf.expanduser().resolve()
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise FlowError(f"不是可读取的 PDF：{pdf}")
    jobs_root = jobs_root.expanduser().resolve()
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_id = datetime.now().strftime("direct-%Y%m%d%H%M%S-") + uuid.uuid4().hex[:8]
    job_dir = jobs_root / job_id
    job_dir.mkdir()

    try:
        document = fitz.open(pdf)
        pages = []
        total_chars = 0
        for number, page in enumerate(document, 1):
            value = _normalize_page(page.get_text("text", sort=True))
            total_chars += len(value)
            pages.append(value)
        page_count = document.page_count
        document.close()
    except Exception as exc:
        raise FlowError(f"PDF 文字层读取失败：{exc}") from exc

    if total_chars < max(80, page_count * 20):
        raise FlowError("PDF 文字层不足；这个极简 skill 不运行 OCR")

    source_markdown = job_dir / "source.md"
    translation_markdown = job_dir / "translation.md"
    _write_text(source_markdown, "\n\n".join(pages).strip() + "\n")
    manifest = {
        "job_id": job_id,
        "source_pdf": str(pdf),
        "source_name": pdf.name,
        "pages": page_count,
        "source_chars": total_chars,
        "source_markdown": str(source_markdown),
        "translation_markdown": str(translation_markdown),
        "state": "ready_for_translation",
    }
    _write_json(job_dir / "job.json", manifest)
    result = {
        "ok": True,
        "job_dir": str(job_dir),
        "source_markdown": str(source_markdown),
        "translation_markdown": str(translation_markdown),
        "pages": page_count,
        "source_chars": total_chars,
        "instruction": (
            "立即只读 source_markdown 一次，完整翻译到 translation_markdown；"
            "使用简体中文，并写含四个指定小节的译者导读。"
            f"本次文字层为 {page_count} 页、{total_chars} 字符，以此为准；"
            "不要用 ls、wc、tail 或第二次读取复核，不要读脚本、OCR、处理图片或另跑检查。"
            "translation_markdown 只允许一次 Write；成功后禁止自审或重写，立即运行 flow.py finalize；"
            "源文若停在半句话就译到该处，不补写；finalize 成功后不要再列目录。"
        ),
    }
    _write_json(job_dir / "prepare.json", result)
    return result


def _inline(value: str) -> str:
    escaped = html.escape(value, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)

    def link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if not url.lower().startswith(("http://", "https://")):
            return label
        return f'<a href="{html.escape(url, quote=True)}">{label}</a>'

    return re.sub(r"\[([^]]+)]\((https?://[^\s)]+)\)", link, escaped)


def _table_cells(line: str) -> list[str]:
    value = line.strip().strip("|")
    return [cell.strip() for cell in value.split("|")]


def _is_table_rule(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _render_markdown(lines: list[str], heading_ids: bool = True) -> tuple[str, list[tuple[int, str, str]]]:
    blocks: list[str] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            index += 1
            continue
        if index + 1 < len(lines) and "|" in line and _is_table_rule(lines[index + 1]):
            flush_paragraph()
            headers = _table_cells(line)
            index += 2
            rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            table = ["<table><thead><tr>"]
            table.extend(f"<th>{_inline(cell)}</th>" for cell in headers)
            table.append("</tr></thead><tbody>")
            for row in rows:
                table.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
            table.append("</tbody></table>")
            blocks.append("".join(table))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = heading.group(2)
            anchor = f"h{len(headings)}" if heading_ids else ""
            attr = f' id="{anchor}"' if anchor else ""
            blocks.append(f"<h{level}{attr}>{_inline(title)}</h{level}>")
            if heading_ids and level >= 2:
                headings.append((level, anchor, title))
            index += 1
            continue
        if stripped in {"---", "***", "___"}:
            flush_paragraph()
            blocks.append("<hr>")
            index += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                quote.append(lines[index].lstrip()[1:].strip())
                index += 1
            blocks.append("<blockquote><p>" + _inline(" ".join(quote)) + "</p></blockquote>")
            continue
        list_match = re.match(r"^\s*(?:[-+*]|\d+[.)])\s+(.+)$", line)
        if list_match:
            flush_paragraph()
            ordered = bool(re.match(r"^\s*\d", line))
            tag = "ol" if ordered else "ul"
            items = []
            while index < len(lines):
                match = re.match(r"^\s*(?:[-+*]|\d+[.)])\s+(.+)$", lines[index])
                if not match or bool(re.match(r"^\s*\d", lines[index])) != ordered:
                    break
                items.append(f"<li>{_inline(match.group(1))}</li>")
                index += 1
            blocks.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        paragraph.append(stripped)
        index += 1
    flush_paragraph()
    return "\n".join(blocks), headings


def _extract_guide(lines: list[str]) -> tuple[list[str], list[str]]:
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^##\s+译者导读\s*$", line.strip())), None)
    if start is None:
        raise FlowError("Markdown 缺少 ## 译者导读")
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"^##\s+", lines[i].strip())), len(lines))
    return lines[:start] + lines[end:], lines[start + 1:end]


def _toc(headings: list[tuple[int, str, str]]) -> str:
    if not headings:
        return ""
    items = []
    for level, anchor, title in headings:
        cls = ' class="l2"' if level == 3 else (' class="l3"' if level == 4 else "")
        items.append(f'<li><a href="#{anchor}"{cls}>{_inline(title)}</a></li>')
    return "<ul>" + "".join(items) + "</ul>"


def finalize(job_dir: Path) -> dict:
    job_dir = job_dir.expanduser().resolve()
    manifest_path = job_dir / "job.json"
    if not manifest_path.is_file():
        raise FlowError(f"不是 direct-paper-translator 任务目录：{job_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    markdown_path = Path(manifest["translation_markdown"])
    if not markdown_path.is_file() or not markdown_path.read_text(encoding="utf-8").strip():
        raise FlowError("translation.md 尚未写入完整译文")
    markdown = markdown_path.read_text(encoding="utf-8")
    lines = [
        line for line in markdown.splitlines()
        if not re.fullmatch(r"\s*〖原页\s+\d+〗\s*", line)
    ]
    title_match = next((re.match(r"^#\s+(.+)$", line.strip()) for line in lines
                        if re.match(r"^#\s+", line.strip())), None)
    if title_match is None:
        raise FlowError("Markdown 缺少 # 中文标题")
    title = title_match.group(1).strip()
    author = next((line.strip() for line in lines[:24]
                   if re.match(r"^作者[：:]", line.strip())), "")
    source = next((line.strip() for line in lines[:24]
                   if re.match(r"^(?:来源|出处|收录于)[：:]", line.strip())), manifest["source_name"])
    body_lines, guide_lines = _extract_guide(lines)
    required_guide_headings = (
        "主要内容", "研究方法", "存在的缺陷与局限", "值得关注的地方"
    )
    missing_guide = [
        heading for heading in required_guide_headings
        if not any(line.strip() == f"### {heading}" for line in guide_lines)
    ]
    if missing_guide:
        raise FlowError("译者导读缺少小节：" + "、".join(missing_guide))
    body_lines = [line for line in body_lines if not (
        re.match(r"^#\s+", line.strip())
        or line.strip() == author
        or line.strip() == source
    )]
    body_html, headings = _render_markdown(body_lines)
    guide_html, _ = _render_markdown(guide_lines, heading_ids=False)
    guide = (
        '<div class="guide"><h2>导读<span class="guide-tag">译者导读</span></h2>'
        + guide_html + "</div>"
    )
    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = template
    replacements = {
        "{{PAGE_TITLE}}": html.escape(title, quote=True),
        "{{TITLE_CN}}": html.escape(title),
        "{{AUTHOR}}": html.escape(author),
        "{{SOURCE}}": html.escape(source),
        "{{GUIDE}}": guide,
        "{{TOC}}": _toc(headings),
        "{{BODY}}": body_html,
    }
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    if re.search(r"{{[A-Z_]+}}", rendered):
        raise FlowError("HTML 模板仍有未替换字段")

    result_dir = job_dir / "result"
    result_md = result_dir / "translation.md"
    result_html = result_dir / "translation.html"
    _write_text(result_md, markdown.rstrip() + "\n")
    _write_text(result_html, rendered)
    manifest.update({
        "state": "completed",
        "result_markdown": str(result_md),
        "result_html": str(result_html),
    })
    _write_json(manifest_path, manifest)
    result = {
        "ok": True,
        "state": "completed",
        "markdown": str(result_md),
        "html": str(result_html),
    }
    _write_json(job_dir / "finalize.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("prepare")
    command.add_argument("pdf", type=Path)
    command.add_argument("--jobs-root", type=Path, required=True)
    command = subparsers.add_parser("finalize")
    command.add_argument("job_dir", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.pdf, args.jobs_root) if args.command == "prepare" else finalize(args.job_dir)
    except (FlowError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
