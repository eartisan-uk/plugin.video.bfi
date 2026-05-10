# -*- coding: utf-8 -*-
"""
Build script for the BFI Player Kodi repository.

Produces everything needed under kodi-repo/ so you can push to GitHub and
have Kodi fetch updates automatically via repository.eartisan.bfi.

Usage (from Windows Command Prompt or PowerShell):
    python make_repo.py

What it does:
  1. Builds plugin.video.bfi-{version}.zip  →  kodi-repo/plugin.video.bfi/
  2. Builds repository.eartisan.bfi-{ver}.zip  →  kodi-repo/repository.eartisan.bfi/
  3. Generates kodi-repo/addons.xml  (parsed from both addon.xml files)
  4. Generates kodi-repo/addons.xml.md5

After running, commit and push kodi-repo/ to GitHub. Kodi will pick up the
update the next time it checks the repository.
"""

import hashlib
import os
import zipfile
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Paths (all relative to this script's directory)
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ADDON_SRC   = os.path.join(BASE_DIR, "plugin.video.bfi-master")
REPO_ADDON  = os.path.join(BASE_DIR, "kodi-repo", "repository.eartisan.bfi")
REPO_OUT    = os.path.join(BASE_DIR, "kodi-repo")

ADDON_ID    = "plugin.video.bfi"
REPO_ID     = "repository.eartisan.bfi"

SKIP_DIRS   = {".git", "__pycache__", ".idea"}
SKIP_EXTS   = {".pyc", ".pyo"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_version(addon_xml_path):
    tree = ET.parse(addon_xml_path)
    return tree.getroot().get("version")


def build_zip(src_dir, addon_id, out_dir):
    """Zip src_dir/ into out_dir/{addon_id}-{version}.zip."""
    version = read_version(os.path.join(src_dir, "addon.xml"))
    zip_name = "{}-{}.zip".format(addon_id, version)
    zip_path = os.path.join(out_dir, zip_name)
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if os.path.splitext(fname)[1] in SKIP_EXTS:
                    continue
                abs_path = os.path.join(root, fname)
                rel      = os.path.relpath(abs_path, src_dir)
                arc_name = os.path.join(addon_id, rel)
                zf.write(abs_path, arc_name)
    print("  Built:", zip_path)
    return version


def build_addons_xml(addon_xml_paths, out_path):
    """Combine multiple addon.xml files into a single addons.xml."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<addons>"]
    for path in addon_xml_paths:
        tree = ET.parse(path)
        root = tree.getroot()
        # Re-serialise with consistent indentation
        ET.indent(root, space="    ")
        xml_str = ET.tostring(root, encoding="unicode")
        # Indent the whole block by 4 spaces
        indented = "\n".join("    " + l for l in xml_str.splitlines())
        lines.append(indented)
    lines.append("</addons>")
    content = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  Written:", out_path)
    return content


def build_md5(content, out_path):
    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md5)
    print("  Written:", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("=== Building plugin zip ===")
plugin_out_dir = os.path.join(REPO_OUT, ADDON_ID)
plugin_version = build_zip(ADDON_SRC, ADDON_ID, plugin_out_dir)

print("\n=== Building repository addon zip ===")
repo_out_dir = os.path.join(REPO_OUT, REPO_ID)
repo_version = build_zip(REPO_ADDON, REPO_ID, repo_out_dir)

print("\n=== Generating addons.xml ===")
addons_xml_path = os.path.join(REPO_OUT, "addons.xml")
addon_xml_files = [
    os.path.join(REPO_ADDON, "addon.xml"),
    os.path.join(ADDON_SRC,  "addon.xml"),
]
content = build_addons_xml(addon_xml_files, addons_xml_path)

print("\n=== Generating addons.xml.md5 ===")
build_md5(content, os.path.join(REPO_OUT, "addons.xml.md5"))

print("\n=== Done ===")
print("plugin.video.bfi  v{}".format(plugin_version))
print("repository.eartisan.bfi  v{}".format(repo_version))
print()
print("Commit and push the kodi-repo/ folder to GitHub.")
print("Users install the repo by pointing Kodi at:")
print("  https://raw.githubusercontent.com/eartisan-uk/plugin.video.bfi/main/kodi-repo/repository.eartisan.bfi/repository.eartisan.bfi-{}.zip".format(repo_version))
