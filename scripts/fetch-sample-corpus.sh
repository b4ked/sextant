#!/usr/bin/env bash
# Download a small, openly available PDF corpus for trying SILO.
# NIST publications are US Government works; the arXiv papers are fetched from arXiv
# for local evaluation only and are not redistributed in this repository.
set -euo pipefail
DEST="${1:-sample-corpus}"
mkdir -p "$DEST"
fetch() { [ -s "$DEST/$1" ] || curl -fsSL --retry 3 -o "$DEST/$1" "$2"; echo "  $1"; }
echo "Fetching sample corpus into $DEST/"
fetch nist-ai-risk-management-framework.pdf   https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf
fetch nist-generative-ai-profile.pdf          https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
fetch nist-cybersecurity-framework-2.0.pdf    https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf
fetch nist-zero-trust-architecture.pdf        https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf
fetch docling-technical-report.pdf            https://arxiv.org/pdf/2408.09869
fetch attention-is-all-you-need.pdf           https://arxiv.org/pdf/1706.03762
echo "Done. Next: silo index $DEST"
