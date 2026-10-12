# -*- coding: utf-8 -*-

"""BenayBIMTools marka dosyalari icin hafif butunluk kontrolu."""

import hashlib
import os

from pyrevit import forms


_VERIFIED = False

# Hash degerleri marka dosyalari son haline getirildikten sonra uretilir.
_PROTECTED_FILES = (
    ("BenayBIMTools.tab/bundle.yaml", "a6ea5801dbd793457ea701e8a4416b5aaae352b7e9a09622b74f2308095ad4e2"),
    ("BenayBIMTools.tab/00_Brand.panel/bundle.yaml", "97ce8b3a5f39f0c5b7ae76210d274b452ad03243ae4897f93f746d76b40edc0f"),
    ("BenayBIMTools.tab/00_Brand.panel/BenayLogo.pushbutton/bundle.yaml", "78fe902a6666d88b457e16408103716f99bb6164020d1d0538ff0e2b914c1309"),
    ("BenayBIMTools.tab/00_Brand.panel/BenayLogo.pushbutton/script.py", "30e805f189fcf4799a7eefd6c7eb2bbf039027014fd061dc883fd2b4c762b4e9"),
    ("BenayBIMTools.tab/00_Brand.panel/BenayLogo.pushbutton/icon.png", "88802db532a98be031f1c857ad348e64dc88cace69d2737e37d4c32c2cff46e5"),
    ("BenayBIMTools.tab/00_Brand.panel/BenayLogo.pushbutton/icon.dark.png", "88802db532a98be031f1c857ad348e64dc88cace69d2737e37d4c32c2cff46e5"),
    ("BenayBIMTools.tab/00_Brand.panel/BenayLogo.pushbutton/brand-logo.png", "ae830446fb691c5ac73f348d33b5c949fb44b3e14595271287604281670cad5e"),
    ("BenayBIMTools.tab/Dimension.panel/ExteriorDimension.pushbutton/bundle.yaml", "80313ea92acff22df47109a2704ea589ffc922dfb185af4021d994dfa588c644"),
    ("BenayBIMTools.tab/Dimension.panel/InteriorDimension.pushbutton/bundle.yaml", "b3fcb0848300ec4dae34c37302946d977bce2999ad076003229b149a45226dc6"),
    ("BenayBIMTools.tab/Dimension.panel/GridDimension.pushbutton/bundle.yaml", "a49db41ccc3ecb2e6d62246d81c5b7772edbb8dfac61415cc233e5e2a090e3d1"),
)


def _extension_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _file_sha256(path):
    digest = hashlib.sha256()
    stream = open(path, "rb")
    try:
        while True:
            block = stream.read(65536)
            if not block:
                break
            digest.update(block)
    finally:
        stream.close()
    return digest.hexdigest()


def _stop_for_integrity_error():
    forms.alert(
        "Benay Kaner BIMTools paket butunlugu dogrulanamadi.\n"
        "Lutfen Benay Kaner tarafindan paylasilan orijinal paketi yeniden kurun.",
        title="Benay Kaner BIMTools",
        warn_icon=True
    )
    raise SystemExit


def verify_brand_integrity():
    """Marka dosyalari degismediyse sessizce devam eder."""
    global _VERIFIED

    if _VERIFIED:
        return True

    root = _extension_root()

    try:
        for relative_path, expected_hash in _PROTECTED_FILES:
            native_path = os.path.join(root, *relative_path.split("/"))
            if not os.path.isfile(native_path):
                _stop_for_integrity_error()
            if _file_sha256(native_path).lower() != expected_hash.lower():
                _stop_for_integrity_error()
    except SystemExit:
        raise
    except:
        _stop_for_integrity_error()

    _VERIFIED = True
    return True
