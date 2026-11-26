"""Regression coverage for quick review, reverse navigation and consensus."""
import array
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import scene_core as core
import scene_sync as sync
from scene_sync_editor import SyncEditor, QuickSyncReview, first_joint_activity, find_joint_activity

class AssignmentTests(unittest.TestCase):
    def test_inherited_links_and_independent_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            media=Path(d)/'audio.wav';media.touch()
            other=Path(d)/'other.wav';other.touch()
            c=core.new_catalog()
            for n in (1,2,3):
                core.add_scene(c,n);core.add_shot(c,n,1)
                u=core.add_subshot(c,n,1,'A')
                core.add_media(c,n,1,media,'audio',subshot_id=u)
            core.configure_links(c,1,member_refs=[core.node_ref(2)])
            groups=core.media_assignments(c,media,'audio')
            self.assertEqual(sorted(len(g['items']) for g in groups),[1,2])
            self.assertEqual([x['target'][0] for x in groups[0]['items']],[1,2])
            self.assertFalse(core.media_assignments(c,other,'audio'))
            self.assertFalse(core.media_assignments(c,media,'video'))

    def test_multiband_promotes_only_distinct_consensus(self):
        f=dict(status='REVIEW',offset=1.,score=.14,valid=2,spread_ms=3,
            temporal_span=4,strong_unique_windows=0,multiband_windows=2,
            outliers=0,outlier_score=0,error='review')
        for scores,expected in [([(.19,1.),(.08,2.)],'OK'),
                                ([(.19,1.),(.18,2.)],'REVIEW')]:
            with patch.object(sync,'spectral_lags',return_value=scores),patch.object(sync,'_fine_candidate',return_value=f.copy()):
                self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.15}])['status'],expected)
        f.update(outliers=1,outlier_score=.35)
        with patch.object(sync,'spectral_lags',return_value=[(.19,1.),(.08,2.)]),patch.object(sync,'_fine_candidate',return_value=f.copy()):
            self.assertEqual(sync.robust_align([],[],[],[],candidates=[{'offset':1.,'waveform':.15}])['status'],'REVIEW')

    def test_confirmation_does_not_prompt(self):
        editor=Mock();editor.offset=1.023456
        with patch('scene_sync_editor.messagebox.askyesno') as dialog:
            SyncEditor.confirm(editor)
            dialog.assert_not_called()
        editor.on_approve.assert_called_once_with(1.023456)
        editor.close.assert_called_once()

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Tk display required')
class GuiTests(unittest.TestCase):
    def test_navigation_and_quick_review(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':d}):
            root=tk.Tk();app=SceneSlateApp(root)
            try:
                v=Path(d)/'v.mov';a=Path(d)/'a.wav';v.touch();a.touch()
                core.add_scene(app.catalog,1);core.add_shot(app.catalog,1,1)
                t,_=core.add_media(app.catalog,1,1,v,'video')
                core.add_media(app.catalog,1,1,a,'audio',take_number=1)
                t['sync']=sync.sync_record('REVIEW',offset_seconds=1.234567,
                    signature=sync.fingerprint(v,a),method=sync.METHOD)
                app.take_filter='none';app.refresh_scene_tree()
                app.go_to_assignment((1,1,None,1),a,'audio')
                self.assertEqual(app.selected_ids(),(1,1))
                self.assertEqual(app.selected_take(),1)
                self.assertEqual(app.active_side,'audio')
                with patch('scene_sync.executables',return_value=('ffmpeg','ffprobe')),patch('scene_slate.QuickSyncReview') as quick:
                    app.quick_review()
                    quick.assert_called_once()
                    quick.call_args.args[4](1.234567)
                self.assertEqual(t['sync']['method'],'manual')
                self.assertEqual(t['sync']['offset_seconds'],1.234567)
                with patch.object(QuickSyncReview,'_load_waveforms',return_value=(array.array('f'),array.array('f'),0.,10.,15.,0.,2.4)),patch.object(QuickSyncReview,'play') as play:
                    q=QuickSyncReview(root,str(v),str(a),t['sync'],lambda _:None,lambda:None)
                    q.queue.put(('load',True,(array.array('f'),array.array('f'),0.,10.,15.,0.,2.4)))
                    q._poll()
                    play.assert_called_once()
                    self.assertAlmostEqual(q.position,2.4)
                    q.close()
            finally:
                app._sync_worker.close();root.destroy()


class ActivityTests(unittest.TestCase):
    def make_signal(self, seconds, active, gain=.1, rate=4000):
        import math
        return array.array('f',(
            (gain if any(lo<=i/rate<hi for lo,hi in active) else .0001)
            *math.sin(i*2*math.pi*310/rate) for i in range(round(seconds*rate))))

    def test_skip_one_sided_sound_and_detect_first_shared_activity(self):
        v=self.make_signal(7,[(.5,1.3),(3,4),(5,6)])
        a=self.make_signal(7,[(1.5,2.3),(3,4),(5,6)],gain=.025)
        self.assertAlmostEqual(first_joint_activity(v,a),3.,delta=.05)

    def test_silence_and_steady_noise_not_accepted(self):
        noise=self.make_signal(5,[(0,5)],gain=.002)
        self.assertIsNone(first_joint_activity(noise,noise))
        self.assertIsNone(first_joint_activity(noise,array.array('f',[0.]*len(noise))))

    def test_scan_respects_signed_offset_and_crosses_chunk_boundary(self):
        from scene_sync_editor import ACTIVITY_RATE
        for offset in (-2.,2.):
            shared=23.
            def pcm(path,start,seconds,rate,fmt,ffmpeg):
                # Shared activity at video t=23, external t=23+offset.
                onset=shared+(offset if path=='audio' else 0)
                return self.make_signal(seconds,[(onset-start,onset-start+1)],rate=rate)
            with patch('scene_sync_editor._ffmpeg_pcm',side_effect=pcm) as decode:
                start=find_joint_activity('video','audio',offset,30.,32.,'ffmpeg')
            self.assertAlmostEqual(start,22.9,delta=.06)
            calls=decode.call_args_list
            self.assertGreaterEqual(len(calls),4)
            self.assertAlmostEqual(calls[1].args[1]-calls[0].args[1],offset)
            self.assertTrue(all(call.args[1]>=0 for call in calls))

    def test_no_overlap_or_cancelled_does_not_decode(self):
        from threading import Event
        stop=Event();stop.set()
        with patch('scene_sync_editor._ffmpeg_pcm') as decode:
            self.assertIsNone(find_joint_activity('v','a',5.,4.,3.,'ffmpeg'))
            self.assertIsNone(find_joint_activity('v','a',0.,4.,4.,'ffmpeg',stop))
            decode.assert_not_called()
