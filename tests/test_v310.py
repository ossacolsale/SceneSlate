import unittest, tempfile, os
from pathlib import Path
from unittest.mock import patch, Mock
import scene_sync as sync
import scene_core as core

class SpectralTests(unittest.TestCase):
    def test_spectral_features_recover_offset_with_gain_eq(self):
        try:import numpy as np
        except ImportError:self.skipTest('NumPy optional')
        r=np.random.default_rng(340);rate=8000
        t=np.arange(rate*16)/rate
        a=np.zeros_like(t)
        for hz in (220,450,750,1450,2500):
            e=np.interp(t,np.arange(81)*.2,r.uniform(.05,1,81))
            a+=e*np.sin(2*np.pi*hz*t+r.uniform(0,6))
        lag=1.37;start=round(rate*lag)
        v=a[start:start+rate*12].copy();v=np.diff(v,prepend=v[0]);v+=.04*r.normal(size=len(v))
        score=sync.spectral_lags(v,a,max_offset_seconds=3)
        best=max(score)
        self.assertAlmostEqual(best[1],lag,delta=.04)
        self.assertGreater(sync.spectral_evidence(score,lag)[1],.1)
        bad=sync.spectral_lags(r.normal(size=len(v)),a,max_offset_seconds=3)
        self.assertLess(max(bad)[0],.20)

    def test_spectral_rescue_requires_unique_evidence_and_consensus(self):
        fine=dict(status='REVIEW',offset=1.0,score=.22,valid=3,spread_ms=2,
                  strong_unique_windows=3,temporal_span=6,outliers=0,error='review')
        with patch.object(sync,'spectral_lags',return_value=[(.55,1.),(.12,2.)]),patch.object(sync,'_fine_candidate',return_value=fine.copy()):
            self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.2}])['status'],'OK')
        with patch.object(sync,'spectral_lags',return_value=[(.55,1.),(.53,2.)]),patch.object(sync,'_fine_candidate',return_value=fine.copy()):
            self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.2}])['status'],'REVIEW')

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Tk display required')
class GuiTests(unittest.TestCase):
    def test_columns_rating_player_and_keyboard(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':d}):
            root=tk.Tk();app=SceneSlateApp(root)
            try:
                core.add_scene(app.catalog,12);core.add_shot(app.catalog,12,3)
                uid=core.add_subshot(app.catalog,12,3,'Close')
                video=Path(d)/'clip with spaces.mov';video.touch()
                core.add_media(app.catalog,12,3,video,'video',subshot_id=uid)
                iid=f'u:12:3:{uid}';app.refresh_scene_tree(iid)
                self.assertEqual(app.scene_tree.item(iid,'text'),'12')
                self.assertEqual(app.scene_tree.set(iid,'shot'),'3')
                self.assertEqual(app.scene_tree.set(iid,'subshot'),'Close')
                self.assertEqual(app.rating_code('B'),'G');self.assertEqual(app.rating_code('S'),'X')
                app.language='it';self.assertEqual(app.rating_code('B'),'B')
                app.language='en';app.video_player='my player.exe'
                with patch('scene_slate.subprocess.Popen') as proc:
                    app.launch_media(video,'video')
                    proc.assert_called_once_with(['my player.exe',str(video.resolve())],shell=False)
                self.assertEqual(app.session_data()['video_player'],'my player.exe')
                from scene_sync_editor import SyncEditor
                editor=Mock();editor.play_active=True
                self.assertEqual(SyncEditor.toggle_playback(editor),'break');editor.stop.assert_called_once()
            finally:root.destroy()
