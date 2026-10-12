# -*- coding: utf-8 -*-

from pyrevit import forms
from benay_integrity import verify_brand_integrity


__author__ = "Benay Kaner"
__copyright__ = "Copyright (c) 2026 Benay Kaner"

verify_brand_integrity()


__title__ = "Benay Kaner\nBIMTools"
__doc__ = "Benay Kaner BIM Tools marka ve eklenti bilgisini gösterir."


forms.alert(
    "BENAY KANER\n"
    "BIM TOOLS\n"
    "BIM WORKFLOW",
    title="BenayBIMTools"
)
