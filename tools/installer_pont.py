"""Installe (ou met à jour) l'extension « Iris (pont) » dans VS Code.

Fabrique le paquet .vsix à partir de pont-vscode/ (un zip, sans npm) puis lance « code --install-extension ».
Usage : .venv/Scripts/python tools/installer_pont.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "pont-vscode"

TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension=".json" ContentType="application/json"/>
<Default Extension=".js" ContentType="application/javascript"/>
<Default Extension=".vsixmanifest" ContentType="text/xml"/>
</Types>"""

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
<Metadata>
<Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}"/>
<DisplayName>{display}</DisplayName>
<Description xml:space="preserve">{description}</Description>
</Metadata>
<Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
<Dependencies/>
<Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>"""


def build(dest):
    pkg = json.loads((SRC / "package.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", TYPES)
        z.writestr("extension.vsixmanifest", MANIFEST.format(
            name=pkg["name"], version=pkg["version"], publisher=pkg["publisher"],
            display=pkg["displayName"], description=pkg["description"]))
        for f in ("package.json", "extension.js"):
            z.write(SRC / f, f"extension/{f}")


def main():
    code = shutil.which("code") or shutil.which("code.cmd")
    if code is None:
        print("VS Code (commande « code ») introuvable")
        return 1
    with tempfile.TemporaryDirectory() as d:
        vsix = Path(d) / "iris-pont.vsix"
        build(vsix)
        r = subprocess.run([code, "--install-extension", str(vsix), "--force"], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
