"""Regression suite for SceneSlate 3.1 tree, metadata, copying and sequential takes."""
import copy
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scene_core as c

class SceneSlate31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.video = self.home / 'C001.mov'; self.video.write_bytes(b'vid')
        self.audio = self.home / 'A001.wav'; self.audio.write_bytes(b'aud')
        self.video2 = self.home / 'C002.mov'; self.video2.write_bytes(b'v2')
        self.cat = c.new_catalog()
        c.add_scene(self.cat, 1)
        c.add_shot(self.cat, 1, 1)

    def test_arbitrary_subshot_names_and_isolation(self):
        a=c.add_subshot(self.cat,1,1,'Inquadratura A')
        b=c.add_subshot(self.cat,1,1,' Dettaglio 3B ')
        self.assertNotEqual(a,b)
        with self.assertRaises(c.CatalogError): c.add_subshot(self.cat,1,1,'inquadratura a')
        pair,changed=c.add_media(self.cat,1,1,self.video,'video',subshot_id=a)
        self.assertEqual(pair['number'],1)
        self.assertEqual(len(c.subshot_for(self.cat,1,1,b)['takes']),0)
        c.rename_subshot(self.cat,1,1,b,'Campo/controcampo')
        self.assertTrue(c.validate(self.cat))
        c.remove_subshot(self.cat,1,1,a)
        self.assertIsNone(c.subshot_for(self.cat,1,1,a))
        self.assertTrue(self.video.exists())
        self.assertIsNotNone(c.shot_for(self.cat,1,1))

    def test_sequential_pairs_and_notes_survive_save(self):
        subid=c.add_subshot(self.cat,1,1,'A')
        sc=c.scene_for(self.cat,1);sc['description']='Interno cucina'
        shot=c.shot_for(self.cat,1,1);shot['description']='Campo lungo'
        sub=c.subshot_for(self.cat,1,1,subid);sub['description']='Camera sinistra'
        first,_=c.add_media(self.cat,1,1,self.video,'video',subshot_id=subid)
        # Audio is paired explicitly, it does not generate a second take.
        second,_=c.add_media(self.cat,1,1,self.audio,'audio',take_number=first['number'],subshot_id=subid)
        self.assertIs(first,second)
        first['description']='Ciak con migliore entrata'
        first['annotation']='Rumore del frigo al secondo 7'
        again,_=c.add_media(self.cat,1,1,self.video2,'video',subshot_id=subid)
        self.assertEqual((first['number'],again['number']),(1,2))
        c.set_take_number(self.cat,1,1,2,9,subshot_id=subid)
        self.assertTrue(again['manual_number'])
        file=self.home/'catalog.json';c.save_catalog(self.cat,file)
        restored=c.load_catalog(file)
        self.assertEqual(c.subshot_for(restored,1,1,subid)['description'],'Camera sinistra')
        pair=c.take_for(restored,1,1,1,subid)
        self.assertEqual(pair['description'],'Ciak con migliore entrata')
        self.assertEqual(pair['annotation'],'Rumore del frigo al secondo 7')
        self.assertEqual(pair['audio']['path'],str(self.audio))
        out=self.home/'out';c.export_all(restored,out)
        with (out/'catalogo_completo.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f,delimiter=';'))
        self.assertEqual(rows[0]['Descrizione scena'],'Interno cucina')
        self.assertEqual(rows[0]['Descrizione shot'],'Campo lungo')
        self.assertEqual(rows[0]['Descrizione sotto-shot'],'Camera sinistra')
        self.assertEqual(rows[0]['Descrizione ciak'],'Ciak con migliore entrata')
        self.assertEqual(rows[0]['Annotazione ciak'],'Rumore del frigo al secondo 7')
        self.assertIn('Rumore del frigo', (out/'resolve_metadata.csv').read_text())

    def test_copy_snapshot_multiple_destinations_and_repeated_media(self):
        subid=c.add_subshot(self.cat,1,1,'A')
        take,_=c.add_media(self.cat,1,1,self.video,'video',subshot_id=subid)
        take,_=c.add_media(self.cat,1,1,self.audio,'audio',take_number=take['number'],subshot_id=subid)
        take['annotation']='Buona luce'
        shot_snapshot=c.node_snapshot(self.cat,1,1)
        c.add_scene(self.cat,2);c.add_shot(self.cat,2,1)
        c.paste_snapshot(self.cat,shot_snapshot,2,1)
        c.paste_snapshot(self.cat,shot_snapshot,2,1)
        dest=c.shot_for(self.cat,2,1)
        self.assertEqual(len(dest['subshots']),2)
        self.assertNotEqual(dest['subshots'][0]['id'],dest['subshots'][1]['id'])
        self.assertEqual(dest['subshots'][0]['name'],'A')
        self.assertTrue(dest['subshots'][1]['name'].startswith('A (copia'))
        self.assertTrue(all(sub['takes'][0]['annotation']=='Buona luce' for sub in dest['subshots']))
        self.assertTrue(all(sub['takes'][0]['video']['path']==str(self.video) for sub in dest['subshots']))
        # Media still exists once on disk and the Resolve CSV cannot assign
        # contradictory scene/take metadata to one Media Pool clip.
        rows, warnings=c.resolve_rows(self.cat)
        self.assertEqual(rows,[])
        self.assertTrue(any('ESCLUSO' in item for item in warnings))
        self.assertTrue(self.video.exists());self.assertTrue(self.audio.exists())

    def test_v3_migration_description_annotation_order_and_backup(self):
        old={'version':3,'name':'Originale','settings':self.cat['settings'],
             'video_root':'','audio_root':'','scenes':[{'number':1,'notes':'Vecchie note scena','shots':[
                 {'number':1,'notes':'Vecchie note shot','takes':[
                     {'number':4,'manual_number':True,'video':{'path':str(self.video),'quality':'B','notes':''},
                      'audio':None,'notes':'Nota sul ciak'}],
                  'subshots':[{'id':'old','name':'A','notes':'Note A','takes':[]}]}]}]}
        filename=self.home/'old.json';filename.write_text(json.dumps(old,ensure_ascii=False))
        restored=c.load_catalog(filename)
        self.assertEqual(restored['version'],4)
        self.assertEqual(restored['scenes'][0]['description'],'Vecchie note scena')
        self.assertEqual(restored['scenes'][0]['shots'][0]['description'],'Vecchie note shot')
        self.assertEqual(restored['scenes'][0]['shots'][0]['subshots'][0]['description'],'Note A')
        take=c.take_for(restored,1,1,4)
        self.assertEqual(take['annotation'],'Nota sul ciak')
        self.assertEqual(take['order'],1)
        c.save_catalog(restored,filename)
        self.assertTrue((self.home/'old.json.v3.bak').is_file())
        self.assertEqual(json.loads(filename.read_text())['version'],4)

    def test_auto_numbering_not_based_on_file_date_and_no_implicit_shift(self):
        a,_=c.add_media(self.cat,1,1,self.video,'video')
        b,_=c.add_media(self.cat,1,1,self.audio,'audio')
        self.assertEqual((a['number'],b['number']),(1,2))
        c.remove_take(self.cat,1,1,1)
        self.assertEqual(b['number'],2)
        d,_=c.add_media(self.cat,1,1,self.video2,'video')
        self.assertEqual(d['number'],3)

    def test_paste_into_subshot_flattens_multiple(self):
        c.add_media(self.cat,1,1,self.video,'video')
        u=c.add_subshot(self.cat,1,1,'B')
        c.add_media(self.cat,1,1,self.audio,'audio',subshot_id=u)
        snap=c.node_snapshot(self.cat,1)
        c.add_shot(self.cat,1,2)
        dst=c.add_subshot(self.cat,1,2,'Finale')
        msg=c.paste_snapshot(self.cat,snap,1,2,dst)
        self.assertIn('ciak',msg)
        takes=c.subshot_for(self.cat,1,2,dst)['takes']
        self.assertEqual([t['number'] for t in takes],[1,2])
        self.assertTrue(c.validate(self.cat))

if __name__ == '__main__':unittest.main()
