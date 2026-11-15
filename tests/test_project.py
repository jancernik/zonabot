from pathlib import Path

import pytest

from zonabot import texts

ROOT = Path(__file__).resolve().parents[1]


def test_b08_requirements_name_the_real_seleniumbase_package():
    names = [line.split("==")[0].strip().lower() for line in (ROOT / "requirements.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert {"seleniumbase", "python-dotenv", "beautifulsoup4", "requests", "psutil"} <= set(names)
    assert "selenium-base" not in names
    assert all("==" in line for line in (ROOT / "requirements.txt").read_text().splitlines() if line and not line.startswith("#"))


@pytest.mark.parametrize("total,text", [
    (0, "Por ahora no encontré publicaciones que se hayan subido hoy. \nVoy a enviarte mensajes cuando aparezcan publicaciones nuevas."),
    (1, "Encontré 1 publicación que se subió hoy. Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."),
    (3, "Encontré 3 publicaciones que se subieron hoy. Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."),
])
def test_baseline_summary_texts_are_unchanged(total, text):
    assert texts.baseline_summary(total) == text


def test_digest_singular_and_plural():
    assert texts.digest(1, "u") == "Y hay 1 publicación nueva más. Miralas en Zonaprop:\nu"
    assert texts.digest(4, "u") == "Y hay 4 publicaciones nuevas más. Miralas en Zonaprop:\nu"
