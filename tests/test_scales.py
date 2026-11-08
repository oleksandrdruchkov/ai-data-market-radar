"""SAI_T визначено лише в core/scales.py, і всі користувачі беруть її звідти."""

import math
import re
from pathlib import Path

import numpy as np

from core import scales
from metrics import autonomy

ROOT = Path(__file__).resolve().parents[1]


def test_reference_and_inverse():
    assert abs(scales.sai_t(scales.REFERENCE_H) - 100.0) < 1e-3
    for h in (0.1, 1.0, 17.41, 2080.0):
        assert abs(scales.hours_at_sai_t(scales.sai_t(h)) - h) < 1e-9
    assert math.isnan(scales.sai_t(0)) and math.isnan(scales.sai_t(-1))
    arr = scales.sai_t(np.array([1.0, 16.0]))
    assert arr.shape == (2,) and arr[0] < arr[1]


def test_ceiling():
    assert scales.beyond_ceiling(17.41) and not scales.beyond_ceiling(16.0)
    assert not scales.beyond_ceiling(None)


def test_metrics_use_shared_formula():
    assert autonomy.sai_t(17.41) == round(scales.sai_t(17.41), 3)


def test_formula_not_duplicated():
    """Ніде, крім core/scales.py, немає власної формули SAI_T чи еталона 124 800."""
    pattern = re.compile(r"log10\s*\(\s*1(\.0)?\s*\+|124[_ ]?800")
    offenders = []
    for path in [ROOT / "app.py", *ROOT.glob("metrics/*.py"), *ROOT.glob("collectors/*.py")]:
        code = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        code = re.sub(r'"""[\s\S]*?"""', "", code)      # докстрінги описують формулу - це не код
        if pattern.search(code):
            offenders.append(path.name)
    assert offenders == []
