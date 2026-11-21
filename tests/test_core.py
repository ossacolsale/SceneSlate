import copy
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scene_core as c

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.dir=Path(self.t.name)
        self.a=self.dir/'media'/'C0001.MOV';self.b=self.dir/'media'/'A0001.WAV'
        self.a.parent.mkdir();self.a.write_bytes(b'video');self.b.write_bytes(b'audio')
        self.cat=c.new_catalog();c.add_scene(self.cat,1);c.add_shot(self.cat,1,1)

    def test_sequential_and_manual_renumbering(self):
        self.assertEqual(c.add_scene(self.cat),2)
        self.assertEqual(c.add_shot(self.cat,1),2)
        with self.assertRaises(c.CatalogError):c.add_scene(self.cat,2)
        c.rename_scene(self.cat,2,12);c.rename_shot(self.cat,1,2,8)
        self.assertIsNotNone(c.shot_for(self.cat,1,8))
        with self.assertRaises(c.CatalogError):c.add_shot(self.cat,1,0)

    def test_explicit_pair_and_independent_qualities(self):
        t,added=c.add_media(self.cat,1,1,self.a,'video')
        self.assertTrue(added)
        self.assertIsNone(t['audio']);self.assertEqual(t['video']['quality'],'B')
        pair,added=c.add_media(self.cat,1,1,self.b,'audio','R',take_number=t['number'])
        self.assertIs(pair,t);self.assertTrue(added)
        self.assertEqual(pair['audio']['quality'],'R')
        self.assertEqual(pair['video']['quality'],'B')
        self.assertFalse(c.add_media(self.cat,1,1,self.a,'video')[1])
        other=self.dir/'media'/'A0002.WAV';other.write_bytes(b'other')
        with self.assertRaises(c.CatalogError):c.add_media(self.cat,1,1,other,'audio',take_number=999)
        rows,warnings=c.resolve_rows(self.cat)
        self.assertEqual(len(rows),2);self.assertFalse(warnings)
        self.assertEqual({r['Take'] for r in rows},{'1'})
        self.assertTrue(any('QUALITY_R' in r['Keywords'] for r in rows))
        self.assertTrue(any('A0001.WAV' in r['Comments'] for r in rows))
        out=self.dir/'export';c.export_all(self.cat,out)
        with (out/'resolve_metadata.csv').open('rb') as f:
            self.assertTrue(f.read().startswith(b'File Name,Clip Directory,Scene,Shot,Take,'))
        with (out/'full_catalog.csv').open(encoding='utf-8-sig',newline='') as f:
            data=list(csv.DictReader(f,delimiter=';'))
        self.assertEqual(len(data),1)
        self.assertEqual(data[0]['Audio quality'],'R')
        self.assertEqual(data[0]['Video exists'],'YES')

    def test_unpaired_export_and_missing_audio(self):
        c.add_media(self.cat,1,1,self.a,'video')
        out=self.dir/'e';c.export_all(self.cat,out)
        with (out/'full_catalog.csv').open(encoding='utf-8-sig',newline='') as f:
            row=list(csv.DictReader(f,delimiter=';'))[0]
        self.assertEqual(row['Audio'],'')
        self.assertEqual(row['Take'],'1')

    def test_pairing_is_explicit_not_guessed(self):
        c.add_media(self.cat,1,1,self.a,'video')
        c.add_media(self.cat,1,1,self.b,'audio')
        sh=c.shot_for(self.cat,1,1)
        self.assertEqual(len(sh['takes']),2)
        self.assertTrue(all(bool(t['video']) != bool(t['audio']) for t in sh['takes']))

    def test_manual_lock_and_automatic_numbering(self):
        t1,_=c.add_media(self.cat,1,1,self.a,'video')
        t2,_=c.add_media(self.cat,1,1,self.b,'audio')
        # New pairs are numbered by insertion, NOT by filesystem timestamps.
        with patch.object(c,'take_time',side_effect=lambda t: 10 if t is t1 else 5):
            self.assertEqual((t1['number'],t2['number']),(1,2))
            new=c.set_take_number(self.cat,1,1,t1['number'],8)
            self.assertEqual(new,8)
            self.assertTrue(t1['manual_number'])
            self.assertEqual(t2['number'],1)
            self.assertEqual(c.reset_take_auto(self.cat,1,1,8),1)
        self.assertFalse(t1['manual_number'])
        self.assertEqual(t2['number'],2)

    def test_duplicate_take_numbers_rejected(self):
        t,_=c.add_media(self.cat,1,1,self.a,'video')
        t2,_=c.add_media(self.cat,1,1,self.b,'audio')
        c.set_take_number(self.cat,1,1,t2['number'],t['number'])
        self.assertTrue(t2['manual_number'])
        self.assertNotEqual(t['number'],t2['number'])
        with self.assertRaises(c.CatalogError):c.set_take_number(self.cat,1,1,t['number'],t2['number'])
        with self.assertRaises(c.CatalogError):c.set_take_number(self.cat,1,1,t['number'],0)

    def test_remove_side_and_resequence(self):
        t,_=c.add_media(self.cat,1,1,self.a,'video')
        t,_=c.add_media(self.cat,1,1,self.b,'audio',take_number=t['number'])
        c.remove_media(self.cat,1,1,t['number'],'audio')
        self.assertEqual(len(c.shot_for(self.cat,1,1)['takes']),1)
        self.assertFalse(c.shot_for(self.cat,1,1)['takes'][0]['audio'])
        c.remove_media(self.cat,1,1,t['number'],'video')
        self.assertEqual(c.shot_for(self.cat,1,1)['takes'],[])

    def test_cross_shot_ambiguity_skipped_from_resolve(self):
        c.add_media(self.cat,1,1,self.a,'video')
        c.add_shot(self.cat,1,2);c.add_media(self.cat,1,2,self.a,'video')
        rows,warnings=c.resolve_rows(self.cat)
        self.assertFalse(rows);self.assertEqual(len(warnings),1);self.assertIn('SKIPPED',warnings[0])

    def test_atomic_save_relative_move(self):
        c.add_media(self.cat,1,1,self.a,'video')
        orig=self.dir/'job'/'catalog.json';orig.parent.mkdir()
        c.save_catalog(self.cat,orig);loaded=c.load_catalog(orig)
        self.assertEqual(loaded['scenes'][0]['shots'][0]['takes'][0]['video']['path'],c.canonical(self.a))
        import shutil
        newroot=self.dir/'moved'
        shutil.copytree(self.dir/'job',newroot/'job')
        shutil.copytree(self.dir/'media',newroot/'media')
        self.a.unlink()
        restored=c.load_catalog(newroot/'job'/'catalog.json')
        self.assertEqual(Path(restored['scenes'][0]['shots'][0]['takes'][0]['video']['path']),Path(c.canonical(newroot/'media'/'C0001.MOV')))

    def test_v1_migration_preserves_media_and_does_not_guess_pair(self):
        old={'version':1,'name':'Legacy','settings':self.cat['settings'],
             'video_root':'','audio_root':'','scenes':[{'number':1,'notes':'','shots':[
                 {'number':1,'notes':'','media':[{'kind':'video','path':str(self.a),'quality':'B','notes':'v'},
                                                   {'kind':'audio','path':str(self.b),'quality':'R','notes':'a'}]}]}]}
        filename=self.dir/'legacy.json';filename.write_text(json.dumps(old))
        migrated=c.load_catalog(filename)
        self.assertEqual(migrated['version'],4)
        takes=migrated['scenes'][0]['shots'][0]['takes']
        self.assertEqual(len(takes),2)
        self.assertEqual(sum(bool(t['video']) for t in takes),1)
        self.assertEqual(sum(bool(t['audio']) for t in takes),1)
        self.assertTrue(all(bool(t['video']) != bool(t['audio']) for t in takes))
        self.assertEqual(sorted(m['quality'] for _,_,_,_,m in c.iter_media(migrated)),['B','R'])
        c.save_catalog(migrated,self.dir/'new.json')
        self.assertEqual(c.load_catalog(self.dir/'new.json')['version'],4)

    def test_v1_backup_created_before_upgrade(self):
        legacy={'version':1,'name':'Old','settings':self.cat['settings'],'video_root':'','audio_root':'',
                'scenes':[{'number':1,'notes':'','shots':[{'number':1,'notes':'',
                'media':[{'kind':'video','path':str(self.a),'quality':'R','notes':''}]}]}]}
        file=self.dir/'legacy.sceneslate.json';original=json.dumps(legacy)
        file.write_text(original)
        migrated=c.load_catalog(file)
        c.save_catalog(migrated,file)
        self.assertEqual((self.dir/'legacy.sceneslate.json.v1.bak').read_text(),original)
        self.assertEqual(json.loads(file.read_text())['version'],4)

    def test_custom_label(self):
        self.cat['settings']={'scene_label':'SC','shot_label':'INQ','separator':' - ','padding':3}
        self.assertEqual(c.label(self.cat,1,1),'SC 001 - INQ 001')

    def test_missing_media_reported(self):
        c.add_media(self.cat,1,1,self.b,'audio');self.b.unlink()
        rows,warnings=c.resolve_rows(self.cat)
        self.assertEqual(len(rows),1);self.assertIn('file not found',warnings[0])

if __name__=='__main__':unittest.main()
