"""Opt-in FFmpeg installer tests using local ZIP fixtures; no network activity."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_dependencies as deps
import scene_session
import scene_sync


class FakeResponse(io.BytesIO):
    def __init__(self,payload,url):
        super().__init__(payload)
        self._url=url
        self.headers={'Content-Length':str(len(payload))}
    def geturl(self):
        return self._url


class DependenciesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        buf=io.BytesIO()
        with ZipFile(buf,'w') as archive:
            archive.writestr('release/bin/ffmpeg.exe',b'FFMPEG_TEST')
            archive.writestr('release/bin/ffprobe.exe',b'FFPROBE_TEST')
            archive.writestr('release/bin/ffplay.exe',b'UNUSED')
            archive.writestr('../../attack-file',b'UNUSED')
        self.archive=buf.getvalue()
        self.checksum=hashlib.sha256(self.archive).hexdigest().encode('ascii')

    def response(self,url,timeout=30):
        if url==deps.ARCHIVE_URL:return FakeResponse(self.archive,url)
        if url==deps.HASH_URL:return FakeResponse(self.checksum,url)
        raise AssertionError('unexpected URL '+url)

    def test_verified_install_and_managed_lookup(self):
        with patch.object(deps.sys,'platform','win32'),\
             patch.object(deps,'_open',side_effect=self.response),\
             patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':str(self.home)},clear=False):
            stages=[]
            ffmpeg,ffprobe=deps.install_windows(callback=lambda *args:stages.append(args))
            self.assertEqual(Path(ffmpeg).read_bytes(),b'FFMPEG_TEST')
            self.assertEqual(Path(ffprobe).read_bytes(),b'FFPROBE_TEST')
            self.assertEqual(deps.managed_executables(),(ffmpeg,ffprobe))
            self.assertFalse(list(self.home.rglob('ffmpeg.zip')))
            self.assertFalse(list(self.home.rglob('attack-file')))
            self.assertIn('ready',[s[0] for s in stages])
            with patch.object(scene_sync.shutil,'which',return_value=None):
                self.assertEqual(scene_sync.executables(),(ffmpeg,ffprobe))

    def test_wrong_hash_never_activates_binary(self):
        def provider(url,timeout=30):
            return FakeResponse(b'0'*64 if url==deps.HASH_URL else self.archive,url)
        with patch.object(deps.sys,'platform','win32'),patch.object(deps,'_open',side_effect=provider):
            with self.assertRaisesRegex(deps.DownloadError,'SHA-256'):
                deps.install_windows(directory=self.home)
        self.assertIsNone(deps.managed_executables(self.home))
        self.assertFalse(list(deps.managed_root(self.home).glob('.install-*')))

    def test_cancel_does_not_activate(self):
        from threading import Event
        cancelled=Event()
        cancelled.set()
        with patch.object(deps.sys,'platform','win32'),patch.object(deps,'_open',side_effect=self.response):
            with self.assertRaisesRegex(deps.DownloadError,'cancelled'):
                deps.install_windows(directory=self.home,cancel=cancelled)
        self.assertIsNone(deps.managed_executables(self.home))

    def test_missing_ffprobe_is_rejected(self):
        buf=io.BytesIO()
        with ZipFile(buf,'w') as archive:archive.writestr('release/bin/ffmpeg.exe',b'A')
        missing=buf.getvalue()
        checksum=hashlib.sha256(missing).hexdigest().encode('ascii')
        def provider(url,timeout=30):
            return FakeResponse(checksum if url==deps.HASH_URL else missing,url)
        with patch.object(deps.sys,'platform','win32'),patch.object(deps,'_open',side_effect=provider):
            with self.assertRaisesRegex(deps.DownloadError,'both ffmpeg.exe'):
                deps.install_windows(directory=self.home)

    def test_windows_only(self):
        with patch.object(deps.sys,'platform','linux'):
            with self.assertRaisesRegex(deps.DownloadError,'Windows only'):
                deps.install_windows(directory=self.home)

    def test_invalid_manifest_cannot_escape_managed_folder(self):
        root=deps.managed_root(self.home)
        root.mkdir(parents=True)
        (root/'active.json').write_text(json.dumps({'directory':'../../escape'}))
        self.assertIsNone(deps.managed_executables(self.home))

    def test_user_reminder_preference(self):
        scene_session.write_state({'ffmpeg_prompt_suppressed':True},self.home)
        self.assertTrue(scene_session.read_state(self.home)['ffmpeg_prompt_suppressed'])


class DependencyPromptTests(unittest.TestCase):
    """UI tests require a display or xvfb-run on Linux."""
    def setUp(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root=tk.Tk()
        self.app=SceneSlateApp(self.root)
        self.addCleanup(self.cleanup)
        self.root.update_idletasks()

    def cleanup(self):
        if self.root.winfo_exists():
            if self.app._session_after_id is not None:
                self.root.after_cancel(self.app._session_after_id)
            self.app.on_root_destroy(type('DestroyEvent',(),{'widget':self.root})())
            self.root.destroy()

    def test_tools_menu_bilingual_and_reminder_toggle(self):
        from scene_i18n import LANGUAGES
        self.assertEqual(self.app.tools_button.cget('text'),'Tools ▾')
        self.assertEqual(self.app.tools_menu.entrycget(0,'label'),'FFmpeg setup…')
        self.app.language_var.set(LANGUAGES['it'])
        self.app.change_language()
        self.assertEqual(self.app.tools_button.cget('text'),'Strumenti ▾')
        self.assertEqual(self.app.tools_menu.entrycget(0,'label'),'Configurazione FFmpeg…')
        self.app._ffmpeg_ask_var.set(False)
        self.app.set_ffmpeg_reminders()
        self.assertTrue(self.app.session_data()['ffmpeg_prompt_suppressed'])

    def test_missing_binaries_prompt_once_per_start_when_enabled(self):
        import tkinter as tk
        with patch.object(scene_sync,'executables',return_value=(None,None)):
            self.app.maybe_prompt_ffmpeg()
            windows=[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
            self.assertEqual(len(windows),1)
            windows[0].destroy()
            self.app._ffmpeg_prompt_suppressed=True
            self.app.maybe_prompt_ffmpeg()
            self.assertFalse(any(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()))

    def test_retry_only_missing_dependency_ko(self):
        import scene_core as core
        c=self.app.catalog
        core.add_scene(c,1)
        core.add_shot(c,1,1)
        t=core.add_take(c,1,1)
        t['video']={'path':str(Path(self.temp.name)/'camera.mov'),'quality':'B'}
        t['audio']={'path':str(Path(self.temp.name)/'rec.wav'),'quality':'B'}
        t['sync']={'status':'KO','error':'FFmpeg and ffprobe are required (install them on PATH)'}
        with patch.object(scene_sync,'executables',return_value=('/fake/ffmpeg','/fake/ffprobe')):
            self.assertEqual(self.app.recover_missing_ffmpeg_sync(),1)
        self.assertIsNone(t['sync'])
        t['sync']={'status':'KO','error':'No reliable waveform match'}
        with patch.object(scene_sync,'executables',return_value=('/fake/ffmpeg','/fake/ffprobe')):
            self.assertEqual(self.app.recover_missing_ffmpeg_sync(),0)
        self.assertEqual(t['sync']['status'],'KO')
