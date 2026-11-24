import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import scene_core as core
import scene_sync as sync

class PatchTests(unittest.TestCase):
    def test_clear_preserves_structure_and_linked_equivalents(self):
        with tempfile.TemporaryDirectory() as d:
            media=Path(d)/'video.mov';media.touch()
            c=core.new_catalog()
            for n in (1,2,3):
                core.add_scene(c,n);core.add_shot(c,n,1);core.add_shot(c,n,2)
                u=core.add_subshot(c,n,1,'Wide')
                core.add_media(c,n,1,media,'video',subshot_id=u)
                core.add_media(c,n,2,media,'video')
            core.configure_links(c,1,member_refs=[core.node_ref(2)])
            u=core.shot_for(c,1,1)['subshots'][0]['id']
            v=core.shot_for(c,3,1)['subshots'][0]['id']
            core.configure_links(c,1,1,u,[core.node_ref(3,1,v)])
            # Configuration of a descendant must not cause deletion of siblings.
            self.assertEqual(core.clear_take_content(c,1,1,u),3)
            for n in (1,2,3):
                self.assertEqual(len(core.shot_for(c,n,1)['subshots']),1)
                self.assertFalse(core.shot_for(c,n,1)['subshots'][0]['takes'])
                self.assertEqual(len(core.shot_for(c,n,2)['takes']),1)
            self.assertTrue(media.exists());core.validate(c)
    def test_two_tight_inliers_rescued_only_with_corroboration(self):
        f=dict(status='REVIEW',offset=1.0,score=.15,valid=2,spread_ms=2,
            strong_unique_windows=2,temporal_span=4,outliers=0,outlier_score=0,error='review')
        for scores,expected in [([(.29,1.),(.12,2.)],'OK'),([(.29,1.),(.28,2.)],'REVIEW')]:
            with patch.object(sync,'spectral_lags',return_value=scores),patch.object(sync,'_fine_candidate',return_value=f.copy()):
                self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.2}])['status'],expected)
        f.update(outliers=1,outlier_score=.4)
        with patch.object(sync,'spectral_lags',return_value=[(.29,1.),(.12,2.)]),patch.object(sync,'_fine_candidate',return_value=f.copy()):
            self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.2}])['status'],'REVIEW')

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Tk display required')
class FlatTests(unittest.TestCase):
    def test_flat_rows_and_clear_undo(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':d}):
            root=tk.Tk();app=SceneSlateApp(root)
            try:
                core.add_scene(app.catalog,1);core.add_shot(app.catalog,1,1)
                media=Path(d)/'video.mov';media.touch()
                core.add_media(app.catalog,1,1,media,'video')
                app.refresh_scene_tree('t:1:1')
                self.assertEqual(app.scene_tree.get_children(),('s:1','t:1:1'))
                with patch('scene_slate.messagebox.askyesno',return_value=True):app.clear_selected_content()
                self.assertFalse(core.shot_for(app.catalog,1,1)['takes'])
                app.undo();self.assertEqual(len(core.shot_for(app.catalog,1,1)['takes']),1)
            finally:root.destroy()
