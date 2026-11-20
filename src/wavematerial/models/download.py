# SPDX-License-Identifier: GPL-2.0-only WITH Universal-FOSS-exception-1.0
"""Download, verify, and install the speech models.

Downloads go to `<cache>/<id>.part` and resume with HTTP Range requests after an
interruption. The finished file must match the manifest's size and sha256 before anything
is installed. Installation builds the model folder beside the final one and renames it into
place, so a model folder is either complete or absent.
"""

from __future__ import annotations

import hashlib
import http.client
import logging
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from wavematerial import __version__
from wavematerial.models.manifest import FileSpec, ModelSpec

CHUNK = 1 << 20  # 1 MiB
USER_AGENT = f"WaveMaterial/{__version__}"

log = logging.getLogger(__name__)

# Called with (bytes done, bytes total). It may raise to cancel the download.
Progress = Callable[[int, int], None]


class DownloadError(Exception):
    """A model could not be downloaded or installed. The message is shown to the user."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def is_installed(spec: ModelSpec, models_dir: Path) -> bool:
    """Quick check for every launch: each file is present with the right size."""
    for f in spec.files:
        p = spec.file(models_dir, f.path)
        if not p.is_file() or p.stat().st_size != f.size:
            return False
    return True


def verify(spec: ModelSpec, models_dir: Path) -> list[str]:
    """Full check (Settings › Verify models): hash every file. Returns the problems found."""
    problems = []
    for f in spec.files:
        p = spec.file(models_dir, f.path)
        if not p.is_file():
            problems.append(f"{spec.name}: {f.path} is missing")
        elif p.stat().st_size != f.size or _sha256_file(p) != f.sha256:
            problems.append(f"{spec.name}: {f.path} is damaged")
    return problems


def _fetch(
    url: str,
    part: Path,
    size: int,
    progress: Progress | None,
    retries: int,
    backoff: float,
    opener: Callable[..., http.client.HTTPResponse],
) -> None:
    """Fill `part` up to `size` bytes, resuming what is already there."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have == size:
            return
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                resuming = have > 0 and resp.status == 206
                if have and not resuming:
                    have = 0  # the server ignored the Range header: start again
                with part.open("ab" if resuming else "wb") as out:
                    while block := resp.read(CHUNK):
                        out.write(block)
                        have += len(block)
                        if progress:
                            progress(have, size)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            last_error = exc
            log.warning("Download of %s interrupted (attempt %d): %s", url, attempt + 1, exc)
    have = part.stat().st_size if part.exists() else 0
    if have != size:
        raise DownloadError(
            f"Could not download {url} ({have} of {size} bytes). Check the internet "
            f"connection and try again; the download resumes where it stopped."
            + (f" Last error: {last_error}" if last_error else "")
        )


def _extract(spec: ModelSpec, archive: Path, dest: Path) -> None:
    """Extract only the listed files, as plain files, checking each one."""
    with tarfile.open(archive, "r:bz2") as tf:
        for f in spec.files:
            name = f"{spec.archive_root}/{f.path}" if spec.archive_root else f.path
            try:
                member = tf.getmember(name)
            except KeyError:
                raise DownloadError(f"{spec.name}: the download has no {f.path}") from None
            if not member.isfile():
                raise DownloadError(f"{spec.name}: {f.path} in the download is not a file")
            src = tf.extractfile(member)
            assert src is not None  # a regular file always has data
            target = dest / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with src, target.open("wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
            _check_file(spec, f, target)


def _check_file(spec: ModelSpec, f: FileSpec, path: Path) -> None:
    if path.stat().st_size != f.size or _sha256_file(path) != f.sha256:
        raise DownloadError(f"{spec.name}: {f.path} does not match the manifest")


def install(
    spec: ModelSpec,
    models_dir: Path,
    cache_dir: Path,
    progress: Progress | None = None,
    *,
    retries: int = 4,
    backoff: float = 2.0,
    opener: Callable[..., http.client.HTTPResponse] = urllib.request.urlopen,
) -> None:
    """Download `spec` if needed, verify it, and install it into `models_dir/<id>/`."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    part = cache_dir / f"{spec.id}.part"

    _fetch(spec.url, part, spec.size, progress, retries, backoff, opener)
    if _sha256_file(part) != spec.sha256:
        part.unlink()
        raise DownloadError(
            f"{spec.name}: the downloaded file is not the expected one (checksum mismatch). "
            f"The upstream file may have changed; a newer WaveMaterial release may be needed."
        )

    staging = models_dir / f".{spec.id}.installing"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        if spec.archive:
            _extract(spec, part, staging)
            part.unlink()
        else:
            target = staging / spec.files[0].path
            target.parent.mkdir(parents=True, exist_ok=True)
            # Already checked: same bytes as the download. move() copies when the models
            # folder is on another drive than the cache.
            shutil.move(part, target)
        final = spec.folder(models_dir)
        if final.exists():
            shutil.rmtree(final)
        staging.replace(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
