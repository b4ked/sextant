"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sextant import __version__
from sextant.config import Settings, load_settings

app = typer.Typer(
    help="Sextant — local-first, CPU-only, air-gapped document search.",
    no_args_is_help=True, add_completion=False, rich_markup_mode=None,
)
models_app = typer.Typer(help="Download and inspect the local models.", no_args_is_help=True)
app.add_typer(models_app, name="models")
console = Console()

HomeOpt = Annotated[Path | None, typer.Option(
    "--home", help="Data directory (models + index). Default: $SEXTANT_HOME or ~/.sextant")]


def _settings(home: Path | None) -> Settings:
    return load_settings(home)


def _ready(settings: Settings):
    from sextant import models

    try:
        models.require(settings)
    except models.ModelsMissing as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"sextant {__version__}")


@models_app.command("pull")
def models_pull(home: HomeOpt = None) -> None:
    """Download parsing, embedding and reranking models. The only command that uses the network."""
    from sextant import models

    settings = _settings(home)
    code = models.pull_in_subprocess(settings)
    if code != 0:
        raise typer.Exit(code)
    _print_models(settings)


@models_app.command("status")
def models_status(home: HomeOpt = None) -> None:
    """Show which models are present on disk."""
    _print_models(_settings(home))


def _print_models(settings: Settings) -> None:
    from sextant import models

    table = Table(title=f"Models in {settings.models_dir}")
    for col in ("role", "model", "present", "size"):
        table.add_column(col)
    for m in models.status(settings):
        table.add_row(m.role, m.name, "[green]yes[/green]" if m.present else "[red]no[/red]",
                      f"{m.size_mb:.0f} MB" if m.present else "—")
    console.print(table)


@app.command()
def index(
    folder: Annotated[Path, typer.Argument(help="Folder (or single file) to index.")],
    force: Annotated[bool, typer.Option("--force", help="Re-parse unchanged files.")] = False,
    ocr: Annotated[bool | None, typer.Option(
        "--ocr/--no-ocr", help="OCR scanned pages and images (slower).")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Summary only (for cron).")] = False,
    home: HomeOpt = None,
) -> None:
    """Index a folder. Safe to re-run: only new and changed files are parsed."""
    settings = _settings(home)
    if ocr is not None:
        settings.ocr = ocr
    _ready(settings)
    from sextant.embed import Embedder
    from sextant.indexer import Indexer
    from sextant.store import IndexMismatch, Store

    store = Store(settings)
    indexer = Indexer(settings, store, Embedder(settings))
    marks = {"indexed": "[green]indexed  [/green]", "unchanged": "[dim]unchanged[/dim]",
             "failed": "[red]failed   [/red]", "empty": "[yellow]empty    [/yellow]",
             "removed": "[yellow]removed  [/yellow]"}

    def on_event(event, position, total):
        if quiet or event.kind == "unchanged":
            return
        detail = ""
        if event.kind == "indexed":
            detail = f"{event.pages or '—'} pages · {event.chunks} chunks · {event.seconds:.1f}s"
        elif event.kind == "failed":
            detail = event.error
        elif event.kind == "empty":
            detail = "no extractable text (scanned? try --ocr)"
        console.print(f"[dim]{position:>4}/{total}[/dim] {marks[event.kind]} "
                      f"{Path(event.path).name}  [dim]{detail}[/dim]", highlight=False)

    console.print(f"Indexing [bold]{folder}[/bold] on CPU ({settings.num_threads} threads, "
                  f"OCR {'on' if settings.ocr else 'off'})")
    try:
        report = indexer.index(folder, force=force, on_event=on_event)
    except (FileNotFoundError, IndexMismatch) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    rate = f" · {report.pages / report.seconds:.1f} pages/s" if report.pages else ""
    console.print(
        f"[bold]Done[/bold] in {report.seconds:.1f}s{rate} — {report.indexed} indexed, "
        f"{report.unchanged} unchanged, {report.empty} empty, {report.failed} failed, "
        f"{report.removed} removed. Index now holds {store.chunk_count()} passages.",
        highlight=False,
    )
    if report.failed:
        raise typer.Exit(1)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="What to look for.")],
    k: Annotated[int, typer.Option("-k", help="Number of results.")] = 5,
    mode: Annotated[str, typer.Option(help="hybrid | semantic | keyword")] = "hybrid",
    rerank: Annotated[bool | None, typer.Option("--rerank/--no-rerank")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    home: HomeOpt = None,
) -> None:
    """Search the index from the terminal."""
    settings = _settings(home)
    _ready(settings)
    result = _searcher(settings).search(query, k=k, mode=mode, rerank=rerank)
    if as_json:
        print(json.dumps(result.to_dict(), indent=2))
        return
    if not result.hits:
        console.print("[yellow]No results.[/yellow]")
        return
    for hit in result.hits:
        _print_hit(hit)
    timing = " · ".join(f"{name} {ms:.0f}ms" for name, ms in result.timings_ms.items())
    console.print(f"[dim]{timing}[/dim]", highlight=False)


def _searcher(settings: Settings):
    from sextant.embed import Embedder
    from sextant.search import Searcher
    from sextant.store import Store

    return Searcher(settings, Store(settings), Embedder(settings))


def _print_hit(hit) -> None:
    page = f" · p.{hit.page_start}" if hit.page_start else ""
    ranks = " ".join(
        part for part in (
            f"vec#{hit.vector_rank}" if hit.vector_rank else "",
            f"bm25#{hit.keyword_rank}" if hit.keyword_rank else "",
            f"rerank {hit.rerank:.2f}" if hit.rerank is not None else "",
        ) if part
    )
    console.print(f"[bold cyan]{hit.rank:>2}[/bold cyan] [bold]{hit.rel_path}[/bold]{page}  "
                  f"[dim]{ranks}[/dim]", highlight=False)
    if hit.headings:
        console.print(f"   [blue]{hit.headings}[/blue]", highlight=False)
    snippet = " ".join(hit.text.split())
    console.print(f"   {snippet[:320]}{'…' if len(snippet) > 320 else ''}\n", highlight=False,
                  markup=False)


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Question to answer from the indexed documents.")],
    home: HomeOpt = None,
) -> None:
    """Answer a question with the configured LLM, citing retrieved passages."""
    settings = _settings(home)
    _ready(settings)
    from sextant.llm import LLMError, egress, stream_answer

    if not settings.llm_enabled:
        console.print("[red]No LLM configured.[/red] Set SEXTANT_LLM_BASE_URL and "
                      "SEXTANT_LLM_MODEL (see docs/llm.md).")
        raise typer.Exit(2)
    from sextant.search import reading_order

    result = reading_order(_searcher(settings).search(question, k=settings.llm_context_chunks))
    if not result.hits:
        console.print("[yellow]Nothing in the index matches that question.[/yellow]")
        return
    console.print(f"[dim]{settings.llm_model} · egress: {egress(settings)}[/dim]\n")
    try:
        for token in stream_answer(settings, question, result.hits):
            console.print(token, end="", highlight=False, markup=False, soft_wrap=True)
    except LLMError as exc:
        console.print(f"\n[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print("\n\n[bold]Sources[/bold]")
    for n, hit in enumerate(result.hits, start=1):
        page = f", p.{hit.page_start}" if hit.page_start else ""
        console.print(f" [{n}] {hit.rel_path}{page}", highlight=False, markup=False)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address. Default 127.0.0.1.")] = None,
    port: Annotated[int | None, typer.Option(help="Port. Default 8321.")] = None,
    home: HomeOpt = None,
) -> None:
    """Start the web interface."""
    import uvicorn

    settings = _settings(home)
    _ready(settings)
    settings.host = host or settings.host
    settings.port = port or settings.port
    from sextant.server import create_app

    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        console.print("[yellow]Warning:[/yellow] binding beyond localhost. The engine has no "
                      "authentication; put it behind a reverse proxy that does.")
    console.print(f"Sextant is at [bold]http://{settings.host}:{settings.port}[/bold]")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")


@app.command()
def status(home: HomeOpt = None) -> None:
    """Show what is in the index."""
    from sextant.store import Store

    settings = _settings(home)
    store = Store(settings)
    stats = store.stats()
    console.print(f"[bold]Index[/bold] {settings.index_dir}")
    console.print(f"  documents {stats['docs']}  (indexed {stats['indexed']}, empty "
                  f"{stats['empty']}, failed {stats['failed']})", highlight=False)
    console.print(f"  pages {stats['pages']}  passages {stats['chunks']}  "
                  f"source size {stats['bytes'] / 1_048_576:.1f} MB", highlight=False)
    for root in store.roots():
        console.print(f"  root: {root}", highlight=False)
    failed = [row for row in store.documents() if row["status"] == "failed"]
    for row in failed:
        console.print(f"  [red]failed[/red] {row['rel_path']}: {row['error']}", highlight=False)


@app.command()
def doctor(home: HomeOpt = None) -> None:
    """Check that this machine is ready to run offline."""
    import os

    from sextant import models
    from sextant.llm import egress

    settings = _settings(home)
    ok = True

    def line(passed: bool, text: str) -> None:
        console.print(f" {'[green]ok  [/green]' if passed else '[red]FAIL[/red]'}  {text}",
                      highlight=False)

    console.print(f"[bold]Sextant {__version__}[/bold] · home {settings.home}")
    for m in models.status(settings):
        ok &= m.present
        line(m.present, f"{m.role} model on disk: {m.name}")
    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    ok &= offline
    line(offline, "model libraries forced offline (HF_HUB_OFFLINE=1)")
    line(True, f"inference device: cpu · {settings.num_threads} threads")
    where = egress(settings)
    if where == "none":
        line(True, "LLM: not configured — no component makes outbound requests")
    elif where in ("loopback", "private"):
        line(True, f"LLM: {settings.llm_model} at {settings.llm_base_url} ({where} address)")
    else:
        console.print(f" [yellow]note[/yellow]  LLM: {settings.llm_model} at "
                      f"{settings.llm_base_url} is EXTERNAL — retrieved passages will leave "
                      "this machine when you use Ask.", highlight=False)
    if not ok:
        raise typer.Exit(1)


@app.command()
def reset(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    home: HomeOpt = None,
) -> None:
    """Delete the index (not the models, and never your documents)."""
    from sextant.store import Store

    settings = _settings(home)
    if not yes:
        typer.confirm(f"Delete the index at {settings.index_dir}?", abort=True)
    Store(settings).reset()
    console.print("Index deleted.")


if __name__ == "__main__":
    app()
