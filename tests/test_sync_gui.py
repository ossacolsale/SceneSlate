"""UI status aggregation, filtering and persistence."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_sync

@unittest.skipUnless(bool(os.environ.get('DISPLAY')) or os.name=='nt','GUI display required')
class SyncGuiTests(unittest.TestCase):
    def test_filter_and_sync_column(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as folder:
            old=os.environ.get('SCENESLATE_CONFIG_DIR')
            os.environ['SCENESLATE_CONFIG_DIR']=str(Path(folder)/'config')
            root=None
            try:
                root=tk.Tk();app=SceneSlateApp(root)
                video=Path(folder)/'v.mov';audio=Path(folder)/'a.wav'
                video.write_bytes(b'video');audio.write_bytes(b'audio')
                for i in (1,2,3):
                    core.add_scene(app.catalog,i);core.add_shot(app.catalog,i,1)
                    t,_=core.add_media(app.catalog,i,1,video,'video')
                    if i<3:
                        core.add_media(app.catalog,i,1,audio,'audio',take_number=1)
                        t['sync']=scene_sync.sync_record('OK' if i==1 else 'KO',
                            offset_seconds=0 if i==1 else None,score=.85 if i==1 else .01,
                            signature=scene_sync.fingerprint(video,audio))
                app.refresh_scene_tree()
                self.assertEqual(app.scene_tree.set('s:1','sync'),'✓ OK')
                self.assertEqual(app.scene_tree.set('s:2','sync'),'✕ KO')
                self.assertEqual(app.scene_tree.set('s:3','sync'),'— SINGLE')
                app.only_unsynced_var.set(True)
                app.scene_filter_changed()
                self.assertFalse(app.scene_tree.exists('s:1'))
                self.assertTrue(app.scene_tree.exists('s:2'))
                self.assertFalse(app.scene_tree.exists('s:3'))  # Single-sided takes are complete
                app.refresh_scene_tree('t:2:1')
                self.assertEqual(app.media_tree.item('1','values')[-1],'✕ KO')
                self.assertEqual(app.session_data()['only_unsynced'],True)
            finally:
                if root:
                    root.destroy()
                if old is None:os.environ.pop('SCENESLATE_CONFIG_DIR',None)
                else:os.environ['SCENESLATE_CONFIG_DIR']=old
