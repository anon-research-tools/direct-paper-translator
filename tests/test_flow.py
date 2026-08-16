import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("direct_flow", ROOT / "scripts" / "flow.py")
flow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)


class FlowTests(unittest.TestCase):
    def test_long_lines_are_split_below_read_tool_limit(self):
        parts = flow._wrap_long_line("这是很长的句子。" * 400)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 1200 for part in parts))

    def test_markdown_is_escaped_and_tables_render(self):
        rendered, headings = flow._render_markdown([
            "## 正文", "", "<script>alert(1)</script>", "",
            "| 项目 | 内容 |", "| --- | --- |", "| A | B |",
        ])
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("<table>", rendered)
        self.assertEqual("正文", headings[0][2])

    def test_finalize_generates_guide_and_html(self):
        with tempfile.TemporaryDirectory() as temp_value:
            job = Path(temp_value)
            translation = job / "translation.md"
            translation.write_text(
                "# 中文标题\n\n作者：甲\n\n来源：某刊\n\n"
                "## 译者导读\n\n### 主要内容\n\n内容。\n\n"
                "### 研究方法\n\n方法。\n\n### 存在的缺陷与局限\n\n局限。\n\n"
                "### 值得关注的地方\n\n关注。\n\n## 正文\n\n译文。\n",
                encoding="utf-8",
            )
            (job / "job.json").write_text(json.dumps({
                "source_name": "paper.pdf",
                "translation_markdown": str(translation),
            }), encoding="utf-8")
            result = flow.finalize(job)
            document = Path(result["html"]).read_text(encoding="utf-8")
            self.assertIn('<div class="guide">', document)
            self.assertIn("<h2", document)
            self.assertIn("中文标题", document)
            self.assertNotRegex(document, r"{{[A-Z_]+}}")

    def test_finalize_removes_legacy_page_markers(self):
        with tempfile.TemporaryDirectory() as temp_value:
            job = Path(temp_value)
            translation = job / "translation.md"
            translation.write_text(
                "# 中文标题\n\n作者：甲\n\n来源：某刊\n\n"
                "## 译者导读\n\n### 主要内容\n\n内容。\n\n"
                "### 研究方法\n\n方法。\n\n### 存在的缺陷与局限\n\n局限。\n\n"
                "### 值得关注的地方\n\n关注。\n\n## 正文\n\n"
                "〖原页 6〗\n\n译文。\n",
                encoding="utf-8",
            )
            (job / "job.json").write_text(json.dumps({
                "source_name": "paper.pdf",
                "translation_markdown": str(translation),
            }), encoding="utf-8")
            result = flow.finalize(job)
            document = Path(result["html"]).read_text(encoding="utf-8")
            self.assertNotIn("〖原页 6〗", document)

    def test_finalize_rejects_incomplete_guide(self):
        with tempfile.TemporaryDirectory() as temp_value:
            job = Path(temp_value)
            translation = job / "translation.md"
            translation.write_text(
                "# 中文标题\n\n## 译者导读\n\n### 主要内容\n\n内容。\n\n"
                "## 正文\n\n译文。\n",
                encoding="utf-8",
            )
            (job / "job.json").write_text(json.dumps({
                "source_name": "paper.pdf",
                "translation_markdown": str(translation),
            }), encoding="utf-8")
            with self.assertRaisesRegex(flow.FlowError, "译者导读缺少小节"):
                flow.finalize(job)


if __name__ == "__main__":
    unittest.main()
