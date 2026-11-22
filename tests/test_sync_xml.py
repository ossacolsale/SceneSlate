"""Tests for waveform matching, status propagation and non-destructive XML export."""
from __future__ import annotations
import array
import csv
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_sync as sync
import scene_xml
from scene_sync_worker import SyncWorker


class SyncMathTests(unittest.TestCase):
    def test_lags_and_unrelated(self):
        rand=random.Random(1)
        video=array.array('f',(rand.uniform(-.4,.4) for _ in range(12*sync.SAMPLE_RATE)))
        external=array.array('f',[0.]*1600+list(video)+[0.]*300)
        offset,score,status,_=sync.estimate_offset(video,external)
        self.assertEqual(status,'OK');self.assertAlmostEqual(offset,2.,places=2)
        offset,score,status,_=sync.estimate_offset(external,video)
        self.assertEqual(status,'OK');self.assertAlmostEqual(offset,-2.,places=2)
        random_audio=array.array('f',(rand.uniform(-.4,.4) for _ in range(len(external))))
        self.assertEqual(sync.estimate_offset(video,random_audio)[2],'KO')
        self.assertEqual(sync.estimate_offset(video,array.array('f',[0.]*len(video)))[2],'KO')

    def test_nonnumpy_fft_fallback(self):
        rand=random.Random(9)
        video=array.array('f',(rand.random()-.5 for _ in range(9*sync.SAMPLE_RATE)))
        external=array.array('f',[0.]*800+list(video))
        with patch.dict(sys.modules,{'numpy':None}):
            offset,score,status,_=sync.estimate_offset(video,external)
        self.assertEqual(status,'OK');self.assertAlmostEqual(offset,1.,places=2)

    def test_fingerprint_invalidates_on_media_change(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);v=p/'v.mov';a=p/'a.wav';v.write_bytes(b'one');a.write_bytes(b'two')
            c=core.new_catalog();core.add_scene(c);core.add_shot(c,1)
            t,_=core.add_media(c,1,1,v,'video')
            core.add_media(c,1,1,a,'audio',take_number=1)
            t['sync']=sync.sync_record('OK',offset_seconds=2.,score=.9,
                signature=sync.fingerprint(v,a))
            self.assertEqual(sync.effective_status(t),'OK')
            a.write_bytes(b'two different')
            self.assertEqual(sync.effective_status(t),'PENDING')
            self.assertEqual(sync.node_status([t]),'PENDING')
            core.remove_media(c,1,1,1,'audio')
            self.assertEqual(sync.effective_status(t),'SINGLE')

    def test_v4_backward_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);v=p/'x.mov';v.write_bytes(b'123')
            c=core.new_catalog();core.add_scene(c);core.add_shot(c,1)
            core.add_media(c,1,1,v,'video')
            c['version']=4;c['settings'].pop('timeline_fps',None)
            for s in c['scenes']:
                for sh in s['shots']:
                    for t in sh['takes']:t.pop('sync',None)
            old=p/'catalog.sceneslate.json'
            old.write_text(json.dumps(c),encoding='utf-8')
            new=core.load_catalog(old)
            self.assertEqual(new['version'],5)
            self.assertIsNone(new['scenes'][0]['shots'][0]['takes'][0]['sync'])
            core.save_catalog(new,old)
            self.assertTrue((p/'catalog.sceneslate.json.v4.bak').is_file())


@unittest.skipUnless(bool(sync.executables()[0]) and bool(sync.executables()[1]),
                     'ffmpeg and ffprobe are required for integration tests')
class MediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name);self.audio=self.p/'external recording.wav';self.video=self.p/'camera clip.mp4'
        rng=random.Random(21);hz=8000
        samples=array.array('h')
        for i in range(16*hz):
            seconds=i/hz
            value=int((0.45+0.4*(i//3000%3==0))*(13000*math.sin(2*math.pi*(190*seconds+8*seconds*seconds))+
                 2200*(rng.random()-.5)))
            samples.append(max(-32768,min(32767,value)))
        with wave.open(str(self.audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(hz)
            wav.writeframes(samples.tobytes())
        subprocess.run([sync.executables()[0],'-v','error','-y','-ss','1.5','-i',str(self.audio),
            '-f','lavfi','-i','color=c=black:s=128x72:r=25','-t','11','-shortest',
            '-c:v','mpeg4','-c:a','aac','-b:a','128k',str(self.video)],
            check=True,capture_output=True,timeout=40)

    def test_detected_sync_and_all_xml_formats(self):
        r=sync.synchronize(self.video,self.audio)
        self.assertEqual(r['status'],'OK',r)
        self.assertAlmostEqual(r['offset_seconds'],1.5,delta=.04)
        cat=core.new_catalog();core.add_scene(cat,1);core.add_shot(cat,1,1)
        sub=core.add_subshot(cat,1,1,'Angle A')
        t,_=core.add_media(cat,1,1,self.video,'video',subshot_id=sub)
        core.add_media(cat,1,1,self.audio,'audio',take_number=1,subshot_id=sub)
        t['sync']=r
        self.assertEqual(sync.node_status([t]),'OK')
        result=core.export_all(cat,self.p/'export',modes=('csv','take','shot','scene'))
        self.assertGreaterEqual(result[0],1)
        xml=list((self.p/'export').rglob('*.xml'))
        self.assertEqual(len(xml),3)
        root=ET.parse(next((self.p/'export'/'xml_takes').glob('*.xml'))).getroot()
        self.assertEqual(root.tag,'xmeml')
        clips=root.findall('.//clipitem')
        self.assertEqual(len(clips),2)
        self.assertEqual(clips[0].findtext('start'),clips[1].findtext('start'))
        self.assertAlmostEqual(int(clips[1].findtext('in'))/25,1.5,delta=.05)
        self.assertEqual(Path(unquote(urlparse(clips[0].findtext('./file/pathurl')).path)).name,self.video.name)
        self.assertTrue((self.p/'export'/'full_catalog.csv').exists())
        with (self.p/'export'/'full_catalog.csv').open(encoding='utf-8-sig',newline='') as handle:
            rows=list(csv.DictReader(handle,delimiter=';'))
        self.assertEqual(rows[0]['Sync status'],'OK')
        self.assertEqual(self.video.stat().st_size,Path(self.video).stat().st_size)

    def test_stereo_external_audio_keeps_two_channels(self):
        stereo=self.p/'stereo recorder.wav'
        with wave.open(str(self.audio),'rb') as source:
            samples=array.array('h');samples.frombytes(source.readframes(source.getnframes()))
        joined=array.array('h')
        for sample in samples:joined.extend((sample,sample))
        with wave.open(str(stereo),'wb') as target:
            target.setnchannels(2);target.setsampwidth(2);target.setframerate(8000)
            target.writeframes(joined.tobytes())
        c=core.new_catalog();core.add_scene(c,1);core.add_shot(c,1)
        t,_=core.add_media(c,1,1,self.video,'video')
        core.add_media(c,1,1,stereo,'audio',take_number=1)
        t['sync']=sync.sync_record('OK',offset_seconds=1.5,score=.96,
            signature=sync.fingerprint(self.video,stereo))
        count=scene_xml.write_timeline(self.p/'stereo.xml','Stereo',[('take1',t)])
        self.assertEqual(count,1)
        root=ET.parse(self.p/'stereo.xml').getroot()
        self.assertEqual(len(root.findall('.//clipitem')),3)
        self.assertEqual([a.findtext('sourcetrack/trackindex') for a in
                          root.findall('.//media/audio/track/clipitem')],['1','2'])

    def test_unverified_audio_is_not_falsely_aligned(self):
        cat=core.new_catalog();core.add_scene(cat,1);core.add_shot(cat,1,1)
        t,_=core.add_media(cat,1,1,self.video,'video')
        core.add_media(cat,1,1,self.audio,'audio',take_number=1)
        counts,warnings=scene_xml.export_timelines(cat,self.p/'export2',modes=('take',))
        self.assertEqual(counts['take'],1)
        clips=ET.parse(next((self.p/'export2'/'xml_takes').glob('*.xml'))).getroot().findall('.//clipitem')
        self.assertEqual(len(clips),1)
        self.assertTrue(any('PENDING' in w for w in warnings))


class WorkerTests(unittest.TestCase):
    def test_worker_deduplicates_pending_fingerprints(self):
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.mov';b=Path(temp)/'b.wav';a.write_bytes(b'');b.write_bytes(b'')
            worker=SyncWorker()
            try:
                self.assertTrue(worker.submit(str(a),str(b)))
                self.assertFalse(worker.submit(str(a),str(b)))
            finally:worker.close()
