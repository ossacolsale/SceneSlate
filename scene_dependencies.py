"""Opt-in, per-user FFmpeg provisioning for SceneSlate on Windows.

No PATH changes or OS package installation. After explicit confirmation SceneSlate
downloads a vendor ZIP, verifies its published SHA-256 and extracts only ffmpeg.exe
and ffprobe.exe. All downloads are run off the Tk UI thread.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import ZipFile, BadZipFile

from scene_session import config_dir

SOURCE_PAGE = 'https://www.gyan.dev/ffmpeg/builds/'
ARCHIVE_URL = SOURCE_PAGE + 'ffmpeg-release-essentials.zip'
HASH_URL = ARCHIVE_URL + '.sha256'
MAX_DOWNLOAD_BYTES = 350 * 1024 * 1024
MAX_UNCOMPRESSED_BINARY = 500 * 1024 * 1024
USER_AGENT = 'SceneSlate/3.4 (FFmpeg user-approved installation)'


class DownloadError(RuntimeError):
    pass


def managed_root(directory=None):
    return Path(directory or config_dir()) / 'tools' / 'ffmpeg'


def managed_executables(directory=None):
    """Return an active pair only if the manifest and both executables exist."""
    base = managed_root(directory)
    try:
        data = json.loads((base / 'active.json').read_text(encoding='utf-8'))
        version = str(data['directory'])
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', version):
            return None
        bin_dir = base / 'versions' / version / 'bin'
        ffmpeg, ffprobe = bin_dir / 'ffmpeg.exe', bin_dir / 'ffprobe.exe'
        return (str(ffmpeg), str(ffprobe)) if ffmpeg.is_file() and ffprobe.is_file() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _open(url, timeout=30):
    request = urllib.request.Request(url, headers={'User-Agent':USER_AGENT})
    response = urllib.request.urlopen(request, timeout=timeout)
    try:
        if urlparse(response.geturl()).scheme != 'https':
            raise DownloadError('The download was redirected to a non-HTTPS URL')
    except Exception:
        response.close()
        raise
    return response


def _digest_from_sidecar(content):
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeError as exc:
        raise DownloadError('The SHA-256 checksum is not valid UTF-8') from exc
    values = re.findall(r'(?<![a-fA-F0-9])[a-fA-F0-9]{64}(?![a-fA-F0-9])',text)
    if len(values) != 1:
        raise DownloadError('Could not read an unambiguous SHA-256 checksum from the vendor')
    return values[0].lower()


def _download_checksum(url):
    with _open(url) as response:
        data = response.read(8193)
    if len(data)>8192:
        raise DownloadError('The vendor SHA-256 response is unexpectedly large')
    return _digest_from_sidecar(data)


def _report(callback,phase,downloaded=0,total=0):
    if callback:callback(phase,downloaded,total)


def _copy_member(archive,member,dest,cancel):
    if member.file_size<=0 or member.file_size>MAX_UNCOMPRESSED_BINARY:
        raise DownloadError('FFmpeg binary has an invalid size')
    written=0
    with archive.open(member) as src, open(dest,'wb') as out:
        while True:
            if cancel is not None and cancel.is_set():
                raise DownloadError('Installation cancelled')
            part=src.read(1024*1024)
            if not part:break
            written+=len(part)
            if written>MAX_UNCOMPRESSED_BINARY:
                raise DownloadError('FFmpeg binary is too large')
            out.write(part)
    if written != member.file_size:
        raise DownloadError('FFmpeg binary is incomplete')


def install_windows(*,directory=None,callback=None,cancel=None,
                    archive_url=ARCHIVE_URL,checksum_url=HASH_URL):
    """Download, verify and activate user-local FFmpeg on a background thread.

    The previous active installation is preserved unless activation succeeds.
    directory overrides the configuration root for isolated tests.
    """
    if sys.platform != 'win32':
        raise DownloadError('Built-in FFmpeg installation is currently available on Windows only')
    base=managed_root(directory)
    base.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.install-',dir=base))
    archive_path=staging/'ffmpeg.zip'
    version='release-'+uuid4().hex[:12]
    activated=False
    try:
        _report(callback,'checksum')
        expected=_download_checksum(checksum_url)
        _report(callback,'download')
        digest=hashlib.sha256()
        downloaded=0
        with _open(archive_url,timeout=40) as response,open(archive_path,'wb') as out:
            size=response.headers.get('Content-Length')
            total=int(size) if size and size.isdecimal() else 0
            if total>MAX_DOWNLOAD_BYTES:
                raise DownloadError('The FFmpeg archive exceeds the permitted download size')
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadError('Installation cancelled')
                chunk=response.read(1024*1024)
                if not chunk:break
                downloaded+=len(chunk)
                if downloaded>MAX_DOWNLOAD_BYTES:
                    raise DownloadError('The FFmpeg archive exceeds the permitted download size')
                out.write(chunk)
                digest.update(chunk)
                _report(callback,'download',downloaded,total)
        if downloaded==0 or digest.hexdigest().lower()!=expected:
            raise DownloadError('FFmpeg archive SHA-256 does not match the published vendor checksum')
        _report(callback,'extract')
        with ZipFile(archive_path) as archive:
            binaries={}
            for item in archive.infolist():
                normalized=item.filename.replace('\\','/')
                parts=normalized.split('/')
                if len(parts)>=3 and parts[-2]=='bin' and parts[-1].lower() in ('ffmpeg.exe','ffprobe.exe'):
                    if parts[-1].lower() in binaries:
                        raise DownloadError('Duplicate FFmpeg executable inside archive')
                    binaries[parts[-1].lower()]=item
            if set(binaries)!={'ffmpeg.exe','ffprobe.exe'}:
                raise DownloadError('Vendor ZIP does not contain both ffmpeg.exe and ffprobe.exe')
            bin_dir=staging/'bin'
            bin_dir.mkdir()
            for name,member in binaries.items():
                _copy_member(archive,member,bin_dir/name,cancel)
        if cancel is not None and cancel.is_set():
            raise DownloadError('Installation cancelled')
        (staging/'SOURCE.txt').write_text(
            'FFmpeg executables provided by Gyan Doshi.\n'
            f'Source: {SOURCE_PAGE}\nArchive: {archive_url}\nSHA-256: {expected}\n'
            'See https://ffmpeg.org/legal.html for licensing and source-code information.\n',
            encoding='utf-8')
        archive_path.unlink(missing_ok=True)
        version_dir=base/'versions'/version
        version_dir.parent.mkdir(parents=True,exist_ok=True)
        os.replace(staging,version_dir)
        activated=True
        marker=base/('active-'+uuid4().hex+'.tmp')
        try:
            marker.write_text(json.dumps({'directory':version}),encoding='utf-8')
            os.replace(marker,base/'active.json')
        finally:
            marker.unlink(missing_ok=True)
        _report(callback,'ready')
        return (str(version_dir/'bin'/'ffmpeg.exe'),str(version_dir/'bin'/'ffprobe.exe'))
    except (BadZipFile,OSError,ValueError) as exc:
        raise DownloadError(str(exc)) from exc
    finally:
        if not activated:
            shutil.rmtree(staging,ignore_errors=True)
