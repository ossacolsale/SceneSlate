"""Linked-node and multiresolution-sync regression tests (no external test packages)."""
from __future__ import annotations
import array
import math
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_sync as sync


class LinkedNodeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video=Path(self.temp.name)/'shot.mov'
        self.audio=Path(self.temp.name)/'audio.wav'
        self.video.write_bytes(b'footage')
        self.audio.write_bytes(b'audio')
        self.c=core.new_catalog()
        core.add_scene(self.c,1);core.add_scene(self.c,2)
        core.add_shot(self.c,1,1);core.add_shot(self.c,1,2);core.add_shot(self.c,2,1)

    def test_links_shots_share_takes_notes_and_manual_number(self):
        t,_=core.add_media(self.c,1,1,self.video,'video')
        core.add_media(self.c,1,1,self.audio,'audio',take_number=t['number'])
        t['description']='close-up'
        core.configure_links(self.c,1,1,None,[core.node_ref(1,2)])
        other=core.shot_for(self.c,1,2)
        self.assertEqual(other['takes'][0]['description'],'close-up')
        self.assertEqual(other['takes'][0]['video']['path'],t['video']['path'])
        core.set_take_number(self.c,1,1,1,7)
        core.propagate_links(self.c,1,1)
        self.assertEqual(other['takes'][0]['number'],7)
        other['takes'][0]['annotation']='linked annotation'
        core.propagate_links(self.c,1,2)
        self.assertEqual(core.take_for(self.c,1,1,7)['annotation'],'linked annotation')
        self.assertTrue(core.validate(self.c))

    def test_unlink_one_member_keeps_independent_content(self):
        core.configure_links(self.c,1,1,None,[core.node_ref(1,2),core.node_ref(2,1)])
        core.configure_links(self.c,1,2,None,[])
        original=core.shot_for(self.c,1,2)
        self.assertIsNone(original.get('link_group'))
        core.shot_for(self.c,1,1)['description']='shared'
        core.propagate_links(self.c,1,1)
        self.assertEqual(core.shot_for(self.c,2,1)['description'],'shared')
        self.assertEqual(original['description'],'')

    def test_subshot_links_and_v5_catalog_migration(self):
        a=core.add_subshot(self.c,1,1,'A')
        b=core.add_subshot(self.c,2,1,'Wide')
        core.configure_links(self.c,1,1,a,[core.node_ref(2,1,b)])
        core.subshot_for(self.c,1,1,a)['description']='sub-shots linked'
        core.propagate_links(self.c,1,1,a)
        self.assertEqual(core.subshot_for(self.c,2,1,b)['description'],'sub-shots linked')
        migrated=core.migrate_legacy({**self.c,'version':5})
        self.assertEqual(migrated['version'],core.VERSION)
        self.assertEqual(core.subshot_for(migrated,2,1,b)['description'],'sub-shots linked')


@unittest.skipUnless(bool(sync.executables()[0]) and bool(sync.executables()[1]),
                     'FFmpeg/ffprobe required for live media integration tests')
class AdvancedSyncMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        rate=8000
        rng=random.Random(1976)
        samples=array.array('h')
        for i in range(rate*17):
            t=i/rate
            burst=(math.sin(2*math.pi*.89*t)*math.sin(2*math.pi*.89*t))**3
            sample=(.20*math.sin(2*math.pi*(171*t+3.4*t*t))+.13*math.sin(2*math.pi*867*t))
            sample+=.03*(rng.random()-.5)
            samples.append(max(-32768,min(32767,int(32767*sample*burst))))
        self.audio=self.root/'recording.wav'
        with wave.open(str(self.audio),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
            f.writeframes(samples.tobytes())

    def camera(self, filename, source, offset, duration=12):
        dest=self.root/filename
        subprocess.run([sync.executables()[0],'-v','error','-y','-ss',str(offset),
           '-i',str(source),'-f','lavfi','-i','color=c=black:s=80x60:r=25',
           '-t',str(duration),'-shortest','-c:v','mpeg4','-c:a','aac','-b:a','96k',str(dest)],
           capture_output=True,check=True,timeout=35)
        return dest

    def test_offset_below_five_milliseconds_and_metadata(self):
        offset=1.037
        video=self.camera('camera.mp4',self.audio,offset)
        result=sync.synchronize(video,self.audio)
        self.assertEqual(result['status'],'OK',result)
        self.assertAlmostEqual(result['offset_seconds'],offset,delta=.005)
        self.assertGreaterEqual(result['windows_verified'],3)
        self.assertEqual(result['method'],'multistage_waveform_v2')
        self.assertLess(result['window_spread_ms'],8)

    def test_unrelated_track_is_not_automatically_ok(self):
        separate=self.root/'unrelated.wav'
        rng=random.Random(42)
        with wave.open(str(separate),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000)
            samples=array.array('h',(int(8000*(rng.random()-.5)) for _ in range(17*8000)))
            f.writeframes(samples.tobytes())
        camera=self.camera('unrelated.mp4',separate,1.23)
        result=sync.synchronize(camera,self.audio)
        self.assertNotEqual(result['status'],'OK',result)

    def test_periodic_audio_is_review_not_wrong_ok(self):
        repetitive=self.root/'repetitive.wav'
        rng=random.Random(891)
        unit=array.array('h',(int(32767*(.14*math.sin(2*math.pi*137*i/8000)+
                   .04*(rng.random()-.5))) for i in range(8000)))
        with wave.open(str(repetitive),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000)
            f.writeframes((unit*18).tobytes())
        video=self.camera('repetitive.mp4',repetitive,1.125)
        result=sync.synchronize(video,repetitive)
        self.assertNotEqual(result['status'],'OK',result)
        self.assertIn(result['status'],('REVIEW','KO'))

    def test_nonnumpy_still_produces_a_verified_alignment(self):
        video=self.camera('fallback.mp4',self.audio,1.041)
        with patch.dict(sys.modules,{'numpy':None}):
            result=sync.synchronize(video,self.audio)
        self.assertEqual(result['status'],'OK',result)
        self.assertAlmostEqual(result['offset_seconds'],1.041,delta=.008)


if __name__=='__main__': unittest.main()
