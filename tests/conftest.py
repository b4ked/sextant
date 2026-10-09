from __future__ import annotations

import os
from pathlib import Path

import pytest

from silo import models
from silo.config import load_settings

REAL_HOME = Path(os.environ.get("SILO_HOME", Path.home() / ".silo")).expanduser()


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("SILO_") and key != "SILO_HOME":
            monkeypatch.delenv(key)
    return load_settings(tmp_path / "home")


@pytest.fixture(scope="session")
def corpus(tmp_path_factory) -> Path:
    """Three small documents with unambiguous facts, built on the fly."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    root = tmp_path_factory.mktemp("corpus")
    styles = getSampleStyleSheet()

    def pdf(name: str, pages: list[list[tuple[str, str]]]) -> None:
        story = []
        for number, page in enumerate(pages):
            if number:
                story.append(PageBreak())
            for heading, body in page:
                story += [Paragraph(heading, styles["Heading1"]), Spacer(1, 8),
                          Paragraph(body, styles["BodyText"]), Spacer(1, 14)]
        SimpleDocTemplate(str(root / name), pagesize=A4).build(story)

    pdf("leave-policy.pdf", [
        [("Annual Leave Policy", "Full-time employees are entitled to 27 days of paid annual "
          "leave each calendar year, in addition to public holidays. Requests are approved by "
          "the line manager.")],
        [("Carrying Days Forward", "Staff may carry forward a maximum of five unused days "
          "into the following year. Carried days expire on 31 March. Reference code HR-LV-0042 "
          "applies to carry-over requests.")],
    ])
    pdf("pump-maintenance.pdf", [
        [("Hydraulic Pump Maintenance", "The hydraulic pump must be inspected every 250 "
          "operating hours. Replace the return-line filter if the differential pressure "
          "indicator shows red.")],
        [("Seal Replacement", "Shaft seals are replaced using kit part number QX-7731-B. "
          "Torque the housing bolts to 45 newton metres in a star pattern.")],
    ])
    (root / "notes").mkdir()
    (root / "notes" / "expenses.md").write_text(
        "# Expenses\n\n## Travel\n\nRail travel is reimbursed at standard class. Claims must be "
        "submitted within 60 days with an itemised receipt.\n\n## Meals\n\nThe overnight meal "
        "allowance is 35 pounds per day.\n"
    )
    (root / ".hidden.md").write_text("# Hidden\n\nThis file must be ignored.\n")
    return root


@pytest.fixture(scope="session")
def real_settings(tmp_path_factory):
    """Settings backed by the real downloaded models, with a throwaway index."""
    probe = load_settings(REAL_HOME)
    if any(not m.present for m in models.status(probe)):
        pytest.skip("models not downloaded; run `silo models pull`")
    home = tmp_path_factory.mktemp("home")
    (home / "models").symlink_to(REAL_HOME / "models")
    return load_settings(home)
