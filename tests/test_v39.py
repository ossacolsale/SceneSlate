"""SceneSlate 3.9: sub-shot-only pairing, linked tooltips and playback cursor."""
from __future__ import annotations

import array
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as core
from scene_sync_editor import SyncEditor


class SubshotRuleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.video = Path(self.dir.name)/'video.mov'
        self.audio = Path(self.dir.name)/'audio.wav'
        self.video.write_bytes(b'video')
        self.audio.write_bytes(b'audio')
        self.catalog = core.new_catalog()
        core.add_scene(self.catalog, 1)
        core.add_shot(self.catalog, 1, 1)
        core.add_shot(self.catalog, 1, 2)

    def test_subshot_prevents_new_direct_takes_and_media(self):
        uid=core.add_subshot(self.catalog, 1, 1, 'Wide')
        with self.assertRaisesRegex(core.CatalogError, 'sub-shot'):
            core.add_take(self.catalog,1,1)
        with self.assertRaisesRegex(core.CatalogError, 'sub-shot'):
            core.add_media(self.catalog,1,1,self.video,'video')
        take,changed=core.add_media(self.catalog,1,1,self.video,'video',subshot_id=uid)
        self.assertTrue(changed)
        self.assertEqual(take['number'],1)
        core.add_media(self.catalog,1,1,self.audio,'audio',take_number=1,subshot_id=uid)
        self.assertEqual(len(core.shot_for(self.catalog,1,1)['takes']),0)

    def test_legacy_direct_takes_remain_without_new_pairing(self):
        direct,_=core.add_media(self.catalog,1,1,self.video,'video')
        core.add_subshot(self.catalog,1,1,'Angle A')
        self.assertIs(direct,core.take_for(self.catalog,1,1,1))
        with self.assertRaises(core.CatalogError):
            core.add_media(self.catalog,1,1,self.audio,'audio',take_number=1)
        core.validate(self.catalog)

    def test_copy_into_shot_with_subshots_cannot_bypass_rule(self):
        core.add_media(self.catalog,1,2,self.audio,'audio')
        original=core.node_snapshot(self.catalog,1,2)
        core.add_subshot(self.catalog,1,1,'Angle A')
        with self.assertRaisesRegex(core.CatalogError,'sub-shot'):
            core.paste_snapshot(self.catalog,original,1,1)
        self.assertFalse(core.shot_for(self.catalog,1,1)['takes'])

    def test_copy_direct_and_subshots_into_same_shot_forbidden(self):
        core.add_media(self.catalog,1,2,self.audio,'audio')
        core.add_subshot(self.catalog,1,2,'Angle B')
        original=core.node_snapshot(self.catalog,1,2)
        with self.assertRaisesRegex(core.CatalogError,'sub-shot'):
            core.paste_snapshot(self.catalog,original,1,1)


@unittest.skipUnless(bool(os.environ.get('DISPLAY')) or os.name == 'nt', 'Tk display unavailable')
class Gui39Tests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        self.dir=tempfile.TemporaryDirectory()
        self.old=os.environ.get('SCENESLATE_CONFIG_DIR')
        os.environ['SCENESLATE_CONFIG_DIR']=self.dir.name
        self.root=tk.Tk()
        self.app=SceneSlateApp(self.root)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.app._sync_worker.close()
        self.root.destroy()
        self.dir.cleanup()
        if self.old is None:os.environ.pop('SCENESLATE_CONFIG_DIR',None)
        else:os.environ['SCENESLATE_CONFIG_DIR']=self.old

    def test_full_linked_names_follow_counts_and_tooltip_contains_every_member(self):
        app=self.app
        for n in (1,2,3,4,5):
            core.add_scene(app.catalog,n)
            core.add_shot(app.catalog,n,1)
        core.configure_links(app.catalog,1,member_refs=[core.node_ref(i) for i in (2,3,4,5)])
        app.refresh_scene_tree()
        row=app.scene_tree.item('s:1','text')
        self.assertLess(row.index('0V / 0A'),row.index('⇄'))
        for n in (2,3,4,5):
            self.assertIn(f'Scene {n}',row)
            self.assertIn(f'Scene {n}',app._link_tooltips['s:1'])
        app._hover_link_id='s:1'
        app._show_link_tooltip('s:1',45,45)
        self.assertTrue(app._hover_link_window.winfo_exists())
        app._hide_link_tooltip()
        self.assertIsNone(app._hover_link_window)

    def test_subshots_reject_shot_drop_without_creating_undo(self):
        app=self.app
        core.add_scene(app.catalog,1)
        core.add_shot(app.catalog,1,1)
        core.add_subshot(app.catalog,1,1,'Angle A')
        file=Path(self.dir.name)/'video.mov';file.write_bytes(b'video')
        with patch('scene_slate.messagebox.showinfo') as alert:
            app.attach_files('video',[str(file)],(1,1,None,None))
        alert.assert_called_once()
        self.assertFalse(app.catalog['scenes'][0]['shots'][0]['takes'])
        self.assertFalse(app.undo_stack)

    def test_playhead_follows_audio_and_scrolls_at_edge(self):
        with patch.object(SyncEditor,'_load_waveforms',return_value=(
                array.array('f',[0.1]*1000),array.array('f',[0.1]*1000),.5,120.,120.,0.)):
            editor=SyncEditor(self.root,'camera','audio',None,lambda _value:None)
        try:
            editor.wave_camera=array.array('f',[.1]*200000)
            editor.wave_external=array.array('f',[.1]*200000)
            editor.wave_camera_range_end=100.
            editor.wave_external_range_end=100.
            editor.duration=editor.full_duration=120.
            editor.position=0.
            editor.view_seconds=10.
            editor.loading=False
            editor.play_active=True
            editor.play_chunk_start=35.
            editor.play_chunk_length=20.
            editor.play_wall_started=100.
            with patch('scene_sync_editor.time.monotonic',return_value=105.), \
                 patch.object(editor,'_request_wave_window'):
                editor._tick_playhead()
            self.assertAlmostEqual(editor.playhead_seconds,40.)
            self.assertAlmostEqual(editor.position,33.)
            self.assertTrue(editor.canvas.find_withtag('playhead'))
            editor.stop()
            self.assertIsNone(editor.cursor_timer)
        finally:
            editor.close()


    def test_waveforms_reload_in_background_for_long_recordings(self):
        with patch.object(SyncEditor,'_load_waveforms',return_value=(
                array.array('f',[.1]*1000),array.array('f',[.1]*1000),.5,360.,360.,0.)):
            editor=SyncEditor(self.root,'camera','audio',None,lambda _value:None)
        try:
            editor.wave_camera=array.array('f',[0.2]*200000)
            editor.wave_external=array.array('f',[0.2]*200000)
            editor.wave_camera_start=editor.wave_external_start=0.
            editor.wave_camera_range_end=editor.wave_external_range_end=100.
            editor.duration=editor.full_duration=360.
            editor.external_duration=360.
            editor.loading=False
            editor.position=205.
            pending=[]
            with patch('scene_sync.executables',return_value=('ffmpeg','ffprobe')), \
                 patch.object(editor,'_schedule_job',side_effect=lambda kind,fn:pending.append((kind,fn))), \
                 patch('scene_sync_editor._ffmpeg_pcm',side_effect=lambda *args:array.array('f',[.2]*100)):
                editor._request_wave_window()
                self.assertTrue(editor.wave_loading)
                self.assertEqual(pending[0][0],'wave')
                item=pending[0][1]()
                self.assertAlmostEqual(item[3],195.)
                self.assertAlmostEqual(item[5],195.)
                editor.queue.put(('wave',True,item))
                editor._poll()
            self.assertAlmostEqual(editor.wave_camera_start,195.)
            self.assertAlmostEqual(editor.wave_external_start,195.)
            self.assertFalse(editor.wave_loading)
        finally:
            editor.close()

    def test_manual_seek_interrupts_active_playback(self):
        with patch.object(SyncEditor,'_load_waveforms',return_value=(
                array.array('f',[.1]*1000),array.array('f',[.1]*1000),.5,120.,120.,0.)):
            editor=SyncEditor(self.root,'camera','audio',None,lambda _value:None)
        try:
            editor.loading=False
            editor.play_active=True
            editor._seek_changed('15')
            self.assertFalse(editor.play_active)
            self.assertEqual(editor.position,15.)
            self.assertEqual(editor.playhead_seconds,15.)
        finally:
            editor.close()


if __name__=='__main__':unittest.main()
