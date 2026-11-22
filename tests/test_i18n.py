"""Locale persistence and language-neutral output regression tests."""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scene_i18n import translate
import scene_core as core
import scene_session as session

class TranslationTests(unittest.TestCase):
    def test_translation_is_not_applied_to_italian_or_user_text(self):
        self.assertEqual(translate('Salva', 'en'), 'Save')
        self.assertEqual(translate('Salva', 'it'), 'Salva')
        self.assertEqual(translate('Nome Z → A','en'), 'Name Z → A')
        self.assertEqual(translate('Descrizione scena:', 'en'), 'Scene description:')
        self.assertEqual(translate('This is my own note.', 'en'), 'This is my own note.')

    def test_export_names_and_headers_are_english(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);video=root/'VID001.mov';video.write_bytes(b'demo')
            catalog=core.new_catalog();core.add_scene(catalog,1);core.add_shot(catalog,1,1)
            core.add_media(catalog,1,1,video,'video')
            core.export_all(catalog,root/'out')
            paths={p.name for p in (root/'out').iterdir()}
            self.assertEqual(paths, {'full_catalog.csv','shot_summary.csv','resolve_metadata.csv','export_report.txt'})
            with (root/'out'/'full_catalog.csv').open(encoding='utf-8-sig',newline='') as f:
                row=next(csv.DictReader(f,delimiter=';'))
            self.assertEqual(row['Scene'], '1')
            self.assertEqual(row['Take'], '1')
            self.assertEqual(row['Video exists'], 'YES')
            self.assertIn('Resolve metadata rows:',(root/'out'/'export_report.txt').read_text())

    def test_legacy_draft_path_still_available(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(session.legacy_draft_file(t).name,'bozza_autosalvata.sceneslate.json')
            self.assertEqual(session.draft_file(t).name,'autosaved_draft.sceneslate.json')

@unittest.skipUnless(bool(os.environ.get('DISPLAY')) or os.name == 'nt','Display required')
class GuiLanguageTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.prev=os.environ.get('SCENESLATE_CONFIG_DIR')
        os.environ['SCENESLATE_CONFIG_DIR']=self.temp.name
        self.addCleanup(self.restore_env)
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.addCleanup(self.close)

    def restore_env(self):
        if self.prev is None:os.environ.pop('SCENESLATE_CONFIG_DIR',None)
        else:os.environ['SCENESLATE_CONFIG_DIR']=self.prev

    def close(self):
        try:
            if self.app._session_after_id:self.root.after_cancel(self.app._session_after_id)
            self.root.destroy()
        except Exception:pass

    def test_english_default_and_live_switch(self):
        self.assertEqual(self.app.language,'en')
        self.assertEqual(self.app.language_var.get(),'English')
        self.assertEqual(self.app.video_browser.tree.heading('#0','text'),'Name')
        self.assertEqual(self.app.video_browser.sort_label_var.get(),'Name A → Z')
        self.assertEqual(self.app.media_tree.heading('take','text'),'Take')
        scene=core.add_scene(self.app.catalog,1);core.add_shot(self.app.catalog,scene,1)
        self.app.refresh_scene_tree('t:1:1')
        self.app.video_browser.sort_label_var.set('Date ↓ (newest first)')
        self.assertEqual(self.app.video_browser.sort_var.get(),'created_desc')
        self.app.language_var.set('Italiano');self.app.change_language()
        self.assertEqual(self.app.video_browser.tree.heading('#0','text'),'Nome')
        self.assertEqual(self.app.video_browser.sort_var.get(),'created_desc')
        self.assertEqual(self.app.video_browser.sort_label_var.get(),'Data ↓ (più recente)')
        self.assertEqual(self.app.media_tree.heading('take','text'),'Ciak')
        self.assertEqual(self.app.selected_ids(),(1,1))
        self.app.save_session()
        self.assertEqual(session.read_state(self.temp.name)['language'],'it')
        self.close()
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.assertEqual(self.app.language,'it')
        self.app.language_var.set('English');self.app.change_language()
        self.assertEqual(self.app.video_browser.sort_var.get(),'created_desc')
        self.assertEqual(self.app.video_browser.tree.heading('#0','text'),'Name')

    def test_legacy_draft_resumes(self):
        self.close()
        path=session.legacy_draft_file(self.temp.name)
        cat=core.new_catalog();core.add_scene(cat,3);core.add_shot(cat,3,2)
        core.save_catalog(cat,path)
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.assertIsNone(self.app.filepath)
        self.assertIsNotNone(core.scene_for(self.app.catalog,3))
        self.assertTrue(self.app.changed_unsaved)

if __name__ == '__main__':unittest.main()
