# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Assemble a release in dist/release/v<version>/, locally. Nothing is uploaded.

    uv run --no-project --python 3.12.13 packaging/release.py

From a clean, pushed commit: builds the Windows installer (packaging/windows/build.py) and the
Linux tarball (packaging/tarball/build.py), adds WaveMaterial's source and the exact sources of
every copyleft library they bundle (packaging/vendored.toml), writes the release notes from
CHANGELOG.md, and SHA256SUMS. Then tag the commit and run packaging/publish.sh on the folder.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import sys
import tarfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bundle import LINUX, REPO, WINDOWS, git, run, vendored, vendored_archive  # noqa: E402

PACKAGING = Path(__file__).resolve().parent


def version() -> str:
    v = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init = (REPO / "src" / "wavematerial" / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{v}"' not in init:
        sys.exit(f"pyproject.toml says {v}, but src/wavematerial/__init__.py disagrees.")
    return v


def changelog(v: str) -> str:
    """The CHANGELOG.md section for version v (its body, without the heading)."""
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(v)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        sys.exit(f"CHANGELOG.md has no section for [{v}].")
    body = re.sub(r"^\[[^\]]+\]: .*$", "", m.group(1), flags=re.M)  # link references
    return body.strip()


def third_party_sources(out: Path, v: str) -> Path:
    """One tar of the copyleft libraries' source archives for every target, plus a manifest."""
    libs: dict[str, dict] = {}
    for target in (WINDOWS, LINUX):
        for lib in vendored(target)[1]:
            if lib.get("source"):
                entry = libs.setdefault(lib["name"], {**lib, "in": []})
                entry["in"].append(target.os)
    lines = [
        f"Sources of the copyleft libraries bundled in WaveMaterial {v}, exactly as built.",
        "Each archive is unchanged from its URL; its sha256 is listed. See",
        "packaging/vendored.toml in WaveMaterial's source for how each one was identified.",
        "",
    ]
    path = out / f"wavematerial-{v}-third-party-sources.tar"
    with tarfile.open(path, "w") as tf:
        for name in sorted(libs, key=str.lower):
            lib = libs[name]
            archive = vendored_archive(lib)
            member = f"wavematerial-{v}-third-party-sources/{archive.name}"
            info = tf.gettarinfo(archive, arcname=member)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            with archive.open("rb") as f:
                tf.addfile(info, f)
            lines += [
                f"{lib['name']} {lib['version']} ({', '.join(lib['in'])})",
                f"  licence: {lib['licence']}",
                f"  file:    {archive.name}",
                f"  from:    {lib['url']}",
                f"  sha256:  {lib['sha256']}",
                "",
            ]
        manifest = "\n".join(lines).encode()
        info = tarfile.TarInfo(f"wavematerial-{v}-third-party-sources/MANIFEST.txt")
        info.size = len(manifest)
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(manifest))
    return path


def main() -> int:
    if git("status", "--porcelain"):
        sys.exit("The working tree has uncommitted changes; a release is built from a commit.")
    head = git("rev-parse", "HEAD")
    if not git("branch", "-r", "--contains", "HEAD"):
        sys.exit("HEAD is not on origin; push it first (the release links to its source).")
    v = version()
    tag = f"v{v}"
    if git("tag", "-l", tag) and git("rev-list", "-n", "1", tag) != head:
        sys.exit(f"Tag {tag} exists and points elsewhere.")
    notes_body = changelog(v)

    out = REPO / "dist" / "release" / tag
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # 1. The packages, each built and tested by its own script.
    run(sys.executable, PACKAGING / "windows" / "build.py")
    run(sys.executable, PACKAGING / "tarball" / "build.py")
    exe = REPO / "dist" / f"WaveMaterial-{v}-windows-x86_64-setup.exe"
    tarball = REPO / "dist" / f"wavematerial-{v}-linux-x86_64.tar.gz"
    for f in (exe, tarball):
        shutil.copy2(f, out / f.name)

    # 2. Sources: ours, and the copyleft libraries'.
    source = out / f"wavematerial-{v}-source.tar.gz"
    run("git", "-C", REPO, "archive", "--format=tar.gz", f"--prefix=wavematerial-{v}/",
        "-o", source, head)  # fmt: skip
    thirdparty = third_party_sources(out, v)

    # 3. Notes, the commit they describe, and checksums.
    (out / "RELEASE_NOTES.md").write_text(
        (PACKAGING / "release-notes.md").read_text(encoding="utf-8").split("-->\n", 1)[1].format(
            changes=notes_body, exe=exe.name, tarball=tarball.name, source=source.name,
            thirdparty=thirdparty.name,
        ),
        encoding="utf-8",
    )  # fmt: skip
    (out / "COMMIT").write_text(head + "\n", encoding="utf-8")
    files = sorted(p for p in out.iterdir() if p.name not in ("RELEASE_NOTES.md", "COMMIT"))
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in files)
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8")

    print(f"\nRelease {tag} assembled in {out}:")
    for p in sorted(out.iterdir()):
        print(f"  {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
    print(f"\nNext: tag the commit ({head[:7]}) as {tag}, push the tag, then run")
    print(f"  packaging/publish.sh {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
