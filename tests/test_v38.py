"""Regression coverage for SceneSlate 3.8: filters, review counts, UI, playback."""
from __future__ import annotations
import array
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_sync as sync


class AggregationTests(unittest.TestCase):
    def test_one_sided_takes_are_intentional_and_not_review_tasks(self):
        s1={'video':{'path':'v'}, 'audio':None}
        s2={'video':None,'audio':{'path':'a'}}
        self.assertEqual(sync.node_status([s1,s2]),'SINGLE')
        self.assertFalse(sync.needs_sync_attention(s1))
        self.assertFalse(sync.needs_sync_attention(s2))
        self.assertEqual(sync.node_status([]),'EMPTY')
        with tempfile.TemporaryDirectory() as d:
            v=Path(d)/'v.mov';a=Path(d)/'a.wav'
            v.write_bytes(b'v');a.write_bytes(b'a')
            pair={'video':{'path':str(v)},'audio':{'path':str(a)}}
            self.assertTrue(sync.needs_sync_attention(pair))
            self.assertEqual(sync.node_status([pair,s1]),'PENDING')
            pair['sync']=sync.sync_record('OK',offset_seconds=0,
                            signature=sync.fingerprint(v,a))
            self.assertEqual(sync.node_status([pair,s1,s2]),'OK')
            self.assertFalse(sync.needs_sync_attention(pair))

    def test_strong_independent_windows_can_pass_two_window_consensus(self):
        # A high-confidence match with two strong unique windows need not be
        # held in REVIEW just because quiet stretches reduced usable windows.
        windows=[{'offset':1.023,'score':.85,'peak_gap':.12,
                  'phat_disagreement_s':.001},
                 {'offset':1.0234,'score':.78,'peak_gap':.15,
                  'phat_disagreement_s':.002},
                 {'offset':1.17,'score':.09,'peak_gap':.005,
                  'phat_disagreement_s':.3},
                 {'offset':1.15,'score':.08,'peak_gap':.002,
                  'phat_disagreement_s':.3}]
        with patch.object(sync,'_fine_window',side_effect=windows):
            v=array.array('f',[.6]*int(18*sync.FINE_RATE))
            result=sync._fine_candidate(v,v,1.02)
        self.assertEqual(result['status'],'OK')
        self.assertAlmostEqual(result['offset'],1.0232,delta=.001)

    def test_repetitive_or_nonunique_peaks_remain_review(self):
        windows=[{'offset':1.02,'score':.86,'peak_gap':.005,
                  'phat_disagreement_s':.001},
                 {'offset':1.0201,'score':.80,'peak_gap':.004,
                  'phat_disagreement_s':.002},
                 {'offset':1.14,'score':.07,'peak_gap':.002,
                  'phat_disagreement_s':.3},
                 {'offset':1.17,'score':.05,'peak_gap':.002,
                  'phat_disagreement_s':.3}]
        with patch.object(sync,'_fine_window',side_effect=windows):
            v=array.array('f',[.6]*int(18*sync.FINE_RATE))
            result=sync._fine_candidate(v,v,1.02)
        self.assertEqual(result['status'],'REVIEW')


@unittest.skipUnless(bool(os.getenv('DISPLAY')) or os.name=='nt','GUI display required')
class Gui38Tests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.temp=tempfile.TemporaryDirectory()
        self.old=os.environ.get('SCENESLATE_CONFIG_DIR')
        os.environ['SCENESLATE_CONFIG_DIR']=str(Path(self.temp.name)/'config')
        self.root=tk.Tk()
        self.app=SceneSlateApp(self.root)
        self.app.startup()

    def tearDown(self):
        self.app._sync_worker.close()
        self.root.destroy()
        self.temp.cleanup()
        if self.old is None:os.environ.pop('SCENESLATE_CONFIG_DIR',None)
        else:os.environ['SCENESLATE_CONFIG_DIR']=self.old

    def test_combined_filters_and_count_ignore_singles(self):
        app=self.app
        video=Path(self.temp.name)/'v.mov';audio=Path(self.temp.name)/'a.wav'
        video.write_bytes(b'v');audio.write_bytes(b'a')
        for n in (1,2,3,4):
            core.add_scene(app.catalog,n);core.add_shot(app.catalog,n,1)
        core.add_media(app.catalog,1,1,video,'video')
        t,_=core.add_media(app.catalog,2,1,video,'video')
        core.add_media(app.catalog,2,1,audio,'audio',take_number=1)
        t['sync']=sync.sync_record('KO',signature=sync.fingerprint(video,audio))
        t,_=core.add_media(app.catalog,3,1,video,'video')
        core.add_media(app.catalog,3,1,audio,'audio',take_number=1)
        t['sync']=sync.sync_record('OK',signature=sync.fingerprint(video,audio))
        app.refresh_scene_tree()
        self.assertIn('1 sync pending/review/KO',app.scene_count_var.get())
        app.sync_filter='attention';app.take_filter='has';app.refresh_scene_tree()
        self.assertFalse(app.scene_tree.exists('s:1'))
        self.assertTrue(app.scene_tree.exists('s:2'))
        self.assertFalse(app.scene_tree.exists('s:3'))
        self.assertFalse(app.scene_tree.exists('s:4'))
        app.sync_filter='EMPTY';app.take_filter='none';app.refresh_scene_tree()
        self.assertTrue(app.scene_tree.exists('s:4'))
        self.assertFalse(app.scene_tree.exists('s:1'))
        app.sync_filter='any';app.take_filter='has';app.refresh_scene_tree()
        self.assertTrue(app.scene_tree.exists('s:1'))
        self.assertFalse(app.scene_tree.exists('s:4'))
        # A mixed node containing an OK paired take plus a one-sided take
        # is still included by the intentional-incomplete filter.
        one_sided={'number':2,'order':2,'manual_number':False,'video':{'path':str(video),'quality':'B'},
                   'audio':None,'description':'','annotation':'','notes':'','sync':None}
        core.shot_for(app.catalog,3,1)['takes'].append(one_sided)
        app.sync_filter='SINGLE';app.take_filter='has';app.refresh_scene_tree()
        self.assertTrue(app.scene_tree.exists('s:1'))
        self.assertTrue(app.scene_tree.exists('s:3'))
        self.assertFalse(app.scene_tree.exists('s:2'))
        self.assertFalse(app.scene_tree.exists('s:4'))
        self.assertIn('Solo audio/video (SINGLE)',__import__('scene_i18n').translate('One-sided (SINGLE)','it'))

    def test_collapse_and_restore(self):
        app=self.app
        self.assertFalse(app.details_expanded)
        self.assertFalse(app.details_content.winfo_manager())
        app.set_details_expanded(True)
        self.assertTrue(app.details_content.winfo_manager())
        state=app.session_data()
        self.assertTrue(state['details_expanded'])
        app.set_details_expanded(False)
        self.assertFalse(app.details_content.winfo_manager())

    def test_linked_badge_lists_actual_destination(self):
        app=self.app
        for n in (1,2,3):
            core.add_scene(app.catalog,n);core.add_shot(app.catalog,n,1)
        core.configure_links(app.catalog,1,None,None,[core.node_ref(2),core.node_ref(3)])
        app.refresh_scene_tree()
        txt=app.scene_tree.item('s:1','text')
        self.assertIn('⇄ S2, S3',txt)
        app.only_unsynced_var.set(False)
        self.assertIn('⇄ S1, S3',app.scene_tree.item('s:2','text'))

    def test_sync_editor_undo_redo_and_unlimited_chunk_scheduling(self):
        from scene_sync_editor import SyncEditor
        from unittest.mock import MagicMock
        # Mock the expensive decoding; this tests Tk state and the playback
        # continuation mechanism, not the OS audio driver.
        with patch.object(SyncEditor,'_load_waveforms',return_value=(
                array.array('f',[0.]*800),array.array('f',[0.]*800),.4,52.)):
            editor=SyncEditor(self.root,'v','a',None,lambda value:None)
            editor._set_offset(.123)
            editor._set_offset(.456)
            editor.undo()
            self.assertAlmostEqual(editor.offset,.123)
            editor.redo()
            self.assertAlmostEqual(editor.offset,.456)
            editor.full_duration=52.
            editor.play_chunk=20
            editor.play_active=True
            serial=editor.generation
            jobs=[]
            with patch.object(editor,'_schedule_job',side_effect=lambda kind,fn:jobs.append((kind,fn))):
                editor._play_next(serial)
                self.assertAlmostEqual(editor.play_cursor,20.)
                editor._play_next(serial)
                self.assertAlmostEqual(editor.play_cursor,40.)
                editor._play_next(serial)
                self.assertAlmostEqual(editor.play_cursor,52.)
                self.assertEqual(len(jobs),3)
                editor._play_next(serial)
                self.assertFalse(editor.play_active)
            editor.close()
