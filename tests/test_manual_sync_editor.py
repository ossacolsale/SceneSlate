"""Precision manual sync: signed offsets, stereo previews and UI persistence."""
from __future__ import annotations
import array
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_sync
from scene_sync_editor import render_preview_wav, SyncEditor

def write_wav(path, samples,rate=8000):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array('h',samples).tobytes())

@unittest.skipUnless(scene_sync.executables()[0], 'FFmpeg needed for audio preview tests')
class PreviewTests(unittest.TestCase):
    def test_positive_offset_aligns_both_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            rng=random.Random(12)
            external=[rng.randrange(-18000,18000) for _ in range(16000)]
            video=p/'camera.wav'
            audio=p/'external.wav'
            target=p/'preview.wav'
            write_wav(video,external[8000:])
            write_wav(audio,external)
            render_preview_wav(video,audio,1.,0,target,scene_sync.executables()[0],duration=.5,rate=8000)
            with wave.open(str(target),'rb') as w:
                self.assertEqual(w.getnchannels(),2)
                result=array.array('h')
                result.frombytes(w.readframes(w.getnframes()))
            self.assertEqual(result[0::2],result[1::2])

    def test_negative_offset_pads_external_with_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            rng=random.Random(34)
            camera=[rng.randrange(-14000,14000) for _ in range(16000)]
            video=p/'video.wav'
            audio=p/'external.wav'
            target=p/'preview.wav'
            write_wav(video,camera)
            write_wav(audio,camera[4000:])
            render_preview_wav(video,audio,-.5,0,target,scene_sync.executables()[0],duration=1.,rate=8000)
            with wave.open(str(target),'rb') as w:
                result=array.array('h')
                result.frombytes(w.readframes(w.getnframes()))
            self.assertTrue(all(x==0 for x in result[1:8000:2]))
            self.assertEqual(result[8001::2],result[8000::2])

    def test_split_mix_camera_and_recorder_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            write_wav(p/'v.wav',[1200]*8000)
            write_wav(p/'a.wav',[2800]*8000)
            for mode,value in [('mix',2000),('camera',1200),('external',2800)]:
                target=p/(mode+'.wav')
                render_preview_wav(p/'v.wav',p/'a.wav',0,0,target,scene_sync.executables()[0],
                                   duration=.25,rate=8000,mode=mode)
                with wave.open(str(target),'rb') as w:
                    result=array.array('h')
                    result.frombytes(w.readframes(w.getnframes()))
                self.assertTrue(all(x==value for x in result))

@unittest.skipUnless(bool(os.getenv('DISPLAY')) or os.name=='nt','Tk display required')
class EditorGuiTests(unittest.TestCase):
    def test_manual_approval_survives_background_result_and_restart(self):
        import tkinter as tk
        from tkinter import ttk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as directory:
            old=os.getenv('SCENESLATE_CONFIG_DIR')
            os.environ['SCENESLATE_CONFIG_DIR']=str(Path(directory)/'profile')
            root=None
            try:
                root=tk.Tk()
                root.withdraw()
                app=SceneSlateApp(root)
                video=Path(directory)/'v.mov'
                audio=Path(directory)/'a.wav'
                video.write_bytes(b'video')
                audio.write_bytes(b'audio')
                core.add_scene(app.catalog,1)
                core.add_shot(app.catalog,1,1)
                take,_=core.add_media(app.catalog,1,1,video,'video')
                core.add_media(app.catalog,1,1,audio,'audio',take_number=1)
                app.refresh_scene_tree('t:1:1')
                app.render_takes(select_take=1)
                with patch.object(SyncEditor,'_load_waveforms',
                    return_value=(array.array('f',[0.]*800),array.array('f',[0.]*800),1.)), \
                    patch('scene_sync_editor.messagebox.askyesno',return_value=True):
                    app.edit_sync()
                    editor=root.winfo_children()[-1]
                    buttons=[]
                    def collect(node):
                        for child in node.winfo_children():
                            if isinstance(child,ttk.Button):buttons.append(child)
                            collect(child)
                    collect(editor)
                    approval=[b for b in buttons if 'Confirm manual alignment' in str(b.cget('text'))]
                    self.assertEqual(len(approval),1)
                    approval[0].invoke()
                self.assertEqual(scene_sync.effective_status(take),'OK')
                self.assertEqual(take['sync']['method'],'manual')
                original=take['sync'].copy()
                key=app._sync_worker.key(video,audio)
                app._sync_worker.output.put((key,scene_sync.sync_record('KO',
                      signature=scene_sync.fingerprint(video,audio))))
                app.poll_sync()
                self.assertEqual(take['sync'],original)
                catalog=Path(directory)/'catalog.json'
                core.save_catalog(app.catalog,catalog)
                loaded=core.load_catalog(catalog)
                verified=core.take_for(loaded,1,1,1)
                self.assertEqual(verified['sync']['method'],'manual')
                self.assertTrue(verified['sync']['manual_verified'])
                app._sync_worker.close()
            finally:
                if root is not None:root.destroy()
                if old is None:os.environ.pop('SCENESLATE_CONFIG_DIR',None)
                else:os.environ['SCENESLATE_CONFIG_DIR']=old
