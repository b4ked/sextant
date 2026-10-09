"""Document parsing and chunking with Docling, pinned to the CPU."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from sextant.config import Settings

# Formats handled without any model (Docling's simple pipeline) plus PDF.
TEXT_SUFFIXES = {".txt", ".text", ".log"}
SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".md", ".csv", ".adoc",
} | TEXT_SUFFIXES
OCR_ONLY_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


@dataclass
class Chunk:
    index: int
    text: str  # the passage as written
    search_text: str  # passage prefixed with its heading path; embedded and keyword-indexed
    headings: list[str] = field(default_factory=list)
    page_start: int = 0  # 0 = format has no pages
    page_end: int = 0


@dataclass
class ParsedDocument:
    title: str
    pages: int
    chunks: list[Chunk]


def supported_suffixes(settings: Settings) -> set[str]:
    return SUPPORTED_SUFFIXES | (OCR_ONLY_SUFFIXES if settings.ocr else set())


class Parser:
    def __init__(self, settings: Settings, tokenizer):
        self.settings = settings
        self._tokenizer = tokenizer
        self._converter = None
        self._chunker = None

    def _build(self) -> None:
        from docling.chunking import HybridChunker
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            RapidOcrOptions,
            TableFormerMode,
        )
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
            PdfFormatOption,
        )
        from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer

        try:  # the weight-loading progress bar is not useful in a batch job
            from transformers.utils import logging as hf_logging

            hf_logging.disable_progress_bar()
        except Exception:  # noqa: BLE001 - purely cosmetic
            pass

        s = self.settings
        opts = PdfPipelineOptions(
            artifacts_path=str(s.docling_dir),
            do_ocr=s.ocr,
            do_table_structure=s.tables,
            document_timeout=s.document_timeout,
            enable_remote_services=False,
            # Sextant's promise is "runs on the CPU you already have": never pick up
            # CUDA or Apple MPS implicitly, so behaviour is the same on every machine.
            accelerator_options=AcceleratorOptions(
                device=AcceleratorDevice.CPU, num_threads=s.num_threads
            ),
        )
        if s.tables:
            opts.table_structure_options.mode = (
                TableFormerMode.ACCURATE if s.table_mode == "accurate" else TableFormerMode.FAST
            )
        if s.ocr:
            opts.ocr_options = RapidOcrOptions()

        formats = [
            InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX, InputFormat.XLSX,
            InputFormat.HTML, InputFormat.MD, InputFormat.CSV, InputFormat.ASCIIDOC,
        ]
        format_options = {InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        if s.ocr:
            formats.append(InputFormat.IMAGE)
            format_options[InputFormat.IMAGE] = ImageFormatOption(pipeline_options=opts)
        self._converter = DocumentConverter(allowed_formats=formats, format_options=format_options)

        raw_tokenizer = self._tokenizer
        max_tokens = s.chunk_tokens

        class _Tokenizer(BaseTokenizer):
            """Sizes chunks with the embedding model's own tokenizer."""

            def count_tokens(self, text: str) -> int:
                return len(raw_tokenizer.encode(text, add_special_tokens=False).ids)

            def get_max_tokens(self) -> int:
                return max_tokens

            def get_tokenizer(self):
                return raw_tokenizer

        self._chunker = HybridChunker(tokenizer=_Tokenizer(), merge_peers=True)

    def parse(self, path: Path) -> ParsedDocument:
        if self._converter is None:
            self._build()
        from docling.datamodel.base_models import ConversionStatus, DocumentStream

        if path.suffix.lower() in TEXT_SUFFIXES:
            # Plain text has no structure to recover; hand it to the Markdown reader.
            data = path.read_bytes().decode("utf-8", errors="replace").encode("utf-8")
            source = DocumentStream(name=path.stem + ".md", stream=io.BytesIO(data))
        else:
            source = path
        result = self._converter.convert(source, raises_on_error=True)
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            raise RuntimeError(f"conversion status: {result.status.value}")
        doc = result.document

        chunks: list[Chunk] = []
        for raw in self._chunker.chunk(dl_doc=doc):
            text = (raw.text or "").strip()
            if not text:
                continue
            pages = sorted(
                {prov.page_no for item in raw.meta.doc_items for prov in (item.prov or [])}
            )
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=text,
                    search_text=self._chunker.contextualize(chunk=raw).strip(),
                    headings=list(raw.meta.headings or []),
                    page_start=pages[0] if pages else 0,
                    page_end=pages[-1] if pages else 0,
                )
            )

        title = ""
        for item, _level in doc.iterate_items():
            label = getattr(getattr(item, "label", None), "value", "")
            if label in {"title", "section_header"} and getattr(item, "text", "").strip():
                title = item.text.strip()
                break
        return ParsedDocument(title=title[:300], pages=len(doc.pages or {}), chunks=chunks)
