"""GUI checks; use xvfb-run -a python3 -m unittest discover -s tests."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scene_core as core


@unittest.skipUnless(bool(os.environ.get('DISPLAY')) or os.name == 'nt', 'Display server required')
class GuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.basedir = Path(self.tmp.name)
        self.old_config = os.environ.get('SCENESLATE_CONFIG_DIR')
        os.environ['SCENESLATE_CONFIG_DIR'] = str(self.basedir / 'config')
        self.addCleanup(self.restore_env)
        self.root = tk.Tk()
        self.app = SceneSlateApp(self.root)
        self.app.startup()
        self.addCleanup(self.cleanup_root)
        self.vid = self.basedir / 'VIDEO'; self.vid.mkdir()
        (self.vid / 'sub').mkdir()
        self.v1 = self.vid / 'C001.mov';self.v1.write_bytes(b'a')
        self.v2 = self.vid / 'C002.mov';self.v2.write_bytes(b'b')
        self.v3 = self.vid / 'sub' / 'C003.mov';self.v3.write_bytes(b'c')
        self.aud = self.basedir / 'AUDIO';self.aud.mkdir()
        self.a1 = self.aud / 'A001.wav';self.a1.write_bytes(b'd')

    def restore_env(self):
        if self.old_config is None:os.environ.pop('SCENESLATE_CONFIG_DIR', None)
        else:os.environ['SCENESLATE_CONFIG_DIR']=self.old_config

    def cleanup_root(self):
        try:
            if self.app._session_after_id is not None:
                self.root.after_cancel(self.app._session_after_id)
                self.app._session_after_id=None
            self.root.destroy()
        except Exception:pass

    def test_filters_and_session_roundtrip(self):
        core.add_scene(self.app.catalog,1);core.add_shot(self.app.catalog,1,1)
        core.add_scene(self.app.catalog,2);core.add_shot(self.app.catalog,2,1)
        core.add_media(self.app.catalog,1,1,self.v1,'video')
        self.app.filepath=str(self.basedir/'mio.sceneslate.json')
        self.app.refresh_scene_tree('t:2:1')
        self.app.changed()
        self.app.video_browser.navigate(self.vid)
        self.app.audio_browser.navigate(self.aud)
        self.app.video_browser.recursive_var.set(True)
        self.app.video_browser.only_unused_var.set(True)
        self.app.video_browser.highlight_unused_var.set(True)
        self.app.video_browser.sort_label_var.set('Data ↓ (più recente)')
        self.app.video_browser.refresh()
        self.assertFalse(self.app.video_browser.tree.exists(core.canonical(self.v1)))
        self.assertTrue(self.app.video_browser.tree.exists(core.canonical(self.v2)))
        self.assertTrue(self.app.video_browser.tree.exists(core.canonical(self.v3)))
        self.assertIn('unused',self.app.video_browser.tree.item(core.canonical(self.v2),'tags'))
        self.app.video_browser.tree.selection_set(core.canonical(self.v2))
        self.app.only_empty_var.set(True)
        self.app.refresh_scene_tree('t:2:1')
        self.assertFalse(self.app.scene_tree.exists('t:1:1'))
        self.assertTrue(self.app.scene_tree.exists('t:2:1'))
        self.assertIn('empty_shot',self.app.scene_tree.item('t:2:1','tags'))
        self.app.audio_browser.filter_var.set('A001')
        self.root.update()
        self.app.save_session()
        self.cleanup_root()
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.root.update()
        self.assertEqual(Path(self.app.filepath),self.basedir/'mio.sceneslate.json')
        self.assertEqual(self.app.selected_ids(),(2,1))
        self.assertTrue(self.app.only_empty_var.get())
        self.assertEqual(self.app.video_browser.sort_var.get(),'created_desc')
        self.assertTrue(self.app.video_browser.recursive_var.get())
        self.assertTrue(self.app.video_browser.only_unused_var.get())
        self.assertEqual(self.app.video_browser.tree.selection(),(core.canonical(self.v2),))
        self.assertEqual(self.app.audio_browser.filter_var.get(),'A001')
        self.assertEqual(self.app.video_browser.path,self.vid)
        self.assertEqual(self.app.audio_browser.path,self.aud)

    def test_pairing_keyboard_side_quality_and_resume(self):
        core.add_scene(self.app.catalog,3);core.add_shot(self.app.catalog,3,2)
        self.app.refresh_scene_tree('t:3:2')
        self.app.attach_files('video',[self.v1],target=(3,2,None))
        self.assertEqual(len(core.shot_for(self.app.catalog,3,2)['takes']),1)
        self.assertIsNotNone(core.shot_for(self.app.catalog,3,2)['takes'][0]['video'])
        first=self.app.media_tree.get_children()[0]
        self.app.media_tree.selection_set(first)
        self.app.on_take_select()
        self.assertEqual(self.app.selected_take(),1)
        self.assertEqual(self.app.switch_side('audio'),'break')
        self.app.attach_files('audio',[self.a1])
        take=core.shot_for(self.app.catalog,3,2)['takes'][0]
        self.assertEqual(take['audio']['path'],str(self.a1))
        self.assertEqual(self.app.set_quality('R'),'break')
        self.assertEqual(take['audio']['quality'],'R')
        self.assertEqual(take['video']['quality'],'B')
        self.app.switch_side('video')
        self.assertEqual(self.app.set_quality('S'),'break')
        self.assertEqual(take['video']['quality'],'S')
        self.app.filepath=str(self.basedir/'pairs.sceneslate.json')
        self.app.changed();self.app.save_session()
        self.cleanup_root()
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.root.update()
        self.assertEqual(self.app.selected_ids(),(3,2))
        self.assertEqual(self.app.selected_take(),1)
        self.assertEqual(self.app.active_side,'video')
        restored=core.shot_for(self.app.catalog,3,2)['takes'][0]
        self.assertEqual(restored['audio']['quality'],'R')
        self.assertEqual(restored['video']['quality'],'S')
        self.app.switch_side('audio')
        self.app.remove_media()
        self.assertIsNone(core.shot_for(self.app.catalog,3,2)['takes'][0]['audio'])
        self.assertTrue(self.a1.is_file())

    def test_descriptions_and_annotations_survive_navigation(self):
        core.add_scene(self.app.catalog,5);core.add_shot(self.app.catalog,5,1)
        uid=core.add_subshot(self.app.catalog,5,1,'A')
        core.add_shot(self.app.catalog,5,2)
        self.app.refresh_scene_tree(f'u:5:1:{uid}')
        self.app.notes_scene_var.set('Cortile')
        self.app.notes_shot_var.set('Campo lungo')
        self.app.notes_subshot_var.set('Primo piano sul volto')
        self.app.attach_files('video',[self.v1],target=(5,1,uid,None))
        self.app.media_tree.selection_set('1')
        self.app.on_take_select()
        self.app.take_description_var.set('Prima ripresa')
        self.app.take_annotation_var.set('Da tagliare in apertura')
        # Switching nodes must commit text from the OLD form to the old node.
        self.app.scene_tree.selection_set('t:5:2')
        self.app.on_scene_select()
        self.assertEqual(core.scene_for(self.app.catalog,5)['description'],'Cortile')
        self.assertEqual(core.shot_for(self.app.catalog,5,1)['description'],'Campo lungo')
        self.assertEqual(core.subshot_for(self.app.catalog,5,1,uid)['description'],'Primo piano sul volto')
        pair=core.take_for(self.app.catalog,5,1,1,uid)
        self.assertEqual(pair['description'],'Prima ripresa')
        self.assertEqual(pair['annotation'],'Da tagliare in apertura')

    def test_delete_subshot_does_not_delete_parent_shot(self):
        from unittest.mock import patch
        core.add_scene(self.app.catalog,7);core.add_shot(self.app.catalog,7,1)
        uid=core.add_subshot(self.app.catalog,7,1,'B')
        self.app.refresh_scene_tree(f'u:7:1:{uid}')
        with patch('scene_slate.messagebox.askyesno',return_value=True):
            self.app.delete_selected()
        self.assertIsNone(core.subshot_for(self.app.catalog,7,1,uid))
        self.assertIsNotNone(core.shot_for(self.app.catalog,7,1))

    def test_unnamed_draft_restored(self):
        core.add_scene(self.app.catalog,11);core.add_shot(self.app.catalog,11,3)
        self.app.refresh_scene_tree('t:11:3');self.app.changed()
        self.app.save_session();self.cleanup_root()
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.root=tk.Tk();self.app=SceneSlateApp(self.root);self.app.startup()
        self.assertIsNone(self.app.filepath)
        self.assertEqual(self.app.selected_ids(),(11,3))
        self.assertIsNotNone(core.shot_for(self.app.catalog,11,3))


if __name__=='__main__':unittest.main()
