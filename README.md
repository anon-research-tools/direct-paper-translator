# Direct Paper Translator

一个面向 OpenCode 的极简学术论文 PDF 翻译 skill：把已有文字层的 PDF 提取成干净文本，生成一份简体中文 Markdown 工作译稿，再套用固定模板生成单文件 HTML。

它适合希望快速得到“能阅读、能保存、能打开”的论文中文初稿的场景。它不是学术定稿工具，也不会替代人工核对。

## 它怎么工作

整个流程只有三步：

1. `prepare` 读取 PDF 已有的文字层，整理空行和超长行，生成任务目录。
2. 模型只读取 `source.md`，一次性按原顺序翻译到 `translation.md`。
3. `finalize` 根据 `assets/paper.html` 生成单文件 HTML。

预处理不会添加 `〖原页 6〗` 这类页码标签；旧任务或模型输出中如果仍有这类标签，生成 HTML 时也会过滤掉。

## 使用前提

- PDF 必须已经有可读取的文字层；
- 本 skill 不运行 OCR，也不识别扫描图片；
- 需要 Python 3 和 PyMuPDF：

```bash
python3 -m pip install PyMuPDF
```

## 命令

在本 skill 目录中运行：

```bash
python3 scripts/flow.py prepare "论文.pdf" --jobs-root "任务目录"
```

命令会返回 `job_dir`、`source_markdown` 和 `translation_markdown`。把完整中文译文写入返回的 `translation_markdown` 后，运行：

```bash
python3 scripts/flow.py finalize "job_dir"
```

最终会得到 Markdown 和 HTML 文件。

Markdown 至少应包含：

- `# 中文标题`；
- `作者：...` 和 `来源：...`；
- `## 译者导读`；
- `### 主要内容`、`### 研究方法`、`### 存在的缺陷与局限`、`### 值得关注的地方`；
- 正文、注释和参考文献。

## 有意保持的简洁边界

本项目不包含 OCR、图片处理、并行翻译、脚注强匹配、术语表、事实核查、多轮 Reviewer 或自动返工。PDF 文字层不足时会直接报告，而不是偷偷切换到 OCR。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 许可

如需公开复用，建议在发布仓库时补充一个明确的开源许可证。没有许可证时，GitHub 上的公开代码默认仍不等于授予他人自由复制、修改和再发布的权利。
