"""Model management: one explicit download step, then everything is local files."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from silo._offline import ALLOW_ENV, network_allowed
from silo.config import Settings


class ModelsMissing(RuntimeError):
    pass


@dataclass
class ModelStatus:
    name: str
    role: str
    path: Path
    present: bool
    size_mb: float


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    # The HF cache layout symlinks snapshot files into blobs/; count each blob once.
    real = {p.resolve() for p in path.rglob("*") if p.is_file()}
    return round(sum(p.stat().st_size for p in real) / 1_048_576, 1)


def _fastembed_model_dir(settings: Settings, model: str) -> Path | None:
    if not settings.fastembed_dir.exists():
        return None
    tail = model.split("/")[-1].lower()
    for child in settings.fastembed_dir.iterdir():
        if child.is_dir() and tail in child.name.lower() and any(child.rglob("*.onnx")):
            return child
    return None


def _fastembed_status(settings: Settings, model: str, role: str) -> ModelStatus:
    found = _fastembed_model_dir(settings, model)
    path = found or settings.fastembed_dir
    return ModelStatus(model, role, path, found is not None, _dir_size_mb(found) if found else 0.0)


def status(settings: Settings) -> list[ModelStatus]:
    docling = settings.docling_dir
    docling_present = docling.exists() and any(docling.rglob("*.safetensors"))
    out = [
        ModelStatus("docling layout + tableformer + rapidocr", "document parsing", docling,
                    docling_present, _dir_size_mb(docling)),
        _fastembed_status(settings, settings.embedding_model, "embeddings"),
    ]
    if settings.rerank:
        out.append(_fastembed_status(settings, settings.reranker_model, "reranking"))
    return out


def require(settings: Settings) -> None:
    missing = [m for m in status(settings) if not m.present]
    if missing:
        names = ", ".join(m.name for m in missing)
        raise ModelsMissing(
            f"Models not found under {settings.models_dir}: {names}.\n"
            "Run `silo models pull` on a machine with internet access, then copy "
            f"{settings.models_dir} to this machine if it is air-gapped."
        )


def pull_in_subprocess(settings: Settings) -> int:
    """Run the download in a child process that is allowed to use the network."""
    env = dict(os.environ)
    env[ALLOW_ENV] = "1"
    env["SILO_HOME"] = str(settings.home)
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        env.pop(key, None)
    return subprocess.call([sys.executable, "-m", "silo.models"], env=env)


def _pull(settings: Settings) -> None:
    if not network_allowed():
        raise RuntimeError("model download requires SILO_ALLOW_NETWORK=1")
    settings.docling_dir.mkdir(parents=True, exist_ok=True)
    settings.fastembed_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] Docling parsing models -> {settings.docling_dir}", flush=True)
    from docling.utils.model_downloader import download_models

    download_models(
        output_dir=settings.docling_dir,
        progress=True,
        with_layout=True,
        with_tableformer=True,
        with_code_formula=False,
        with_picture_classifier=False,
        with_rapidocr=True,
    )

    print(f"[2/3] Embedding model {settings.embedding_model}", flush=True)
    from fastembed import TextEmbedding

    TextEmbedding(settings.embedding_model, cache_dir=str(settings.fastembed_dir))

    print(f"[3/3] Reranker model {settings.reranker_model}", flush=True)
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    TextCrossEncoder(settings.reranker_model, cache_dir=str(settings.fastembed_dir))
    print("Done. Every other silo command now runs without network access.", flush=True)


if __name__ == "__main__":
    from silo.config import load_settings

    _pull(load_settings())
