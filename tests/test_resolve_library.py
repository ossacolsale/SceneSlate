"""Resolve library exporter and mocked internal Lua API (not a Resolve integration test)."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as E
import scene_core as core
import scene_sync as sync
import scene_resolve_library as lib

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.c=core.new_catalog()
        core.add_scene(self.c,3)
        core.add_shot(self.c,3,1)
        core.add_shot(self.c,3,2)
        core.add_shot(self.c,3,3)
        core.add_scene(self.c,4)
        core.add_shot(self.c,4,1)

    def media(self,name):
        p=self.base/name;p.touch();return p

    def add(self,shot,vq='B',aq='B',state='OK',offset=-6.939585,method='waveform',video=None,scene=3,sub=None):
        v=video or self.media(f'v{scene}-{shot}-{len(list(core.iter_media_context(self.c)))}.mp4')
        a=self.media(f'a{scene}-{shot}-{len(list(core.iter_media_context(self.c)))}.wav')
        t,_=core.add_media(self.c,scene,shot,v,'video',vq,subshot_id=sub)
        core.add_media(self.c,scene,shot,a,'audio',aq,take_number=t['number'],subshot_id=sub)
        t['sync']=sync.sync_record(state,offset_seconds=offset,method=method,signature=sync.fingerprint(v,a))
        return t

    def probe(self,path,exe):
        v=Path(path).suffix.lower()=='.mp4'
        return dict(path=str(Path(path).resolve()),duration=38.4,fps='25' if v else None,
            timecode='05:25:20:12' if v else '',
            video=dict(width=3840,height=2160,color_primaries='bt2020') if v else None,
            audio=[dict(channels=2 if v else 1,sample_rate='48000',bits_per_sample=24)],
            raw={'streams':[]})

    def test_quality_independent_per_angle_and_selection(self):
        self.add(1,'B','S');self.add(1,'R','B');self.add(1,'S','B')
        self.add(2,'R','R');self.add(2,'R','B')
        u=core.add_subshot(self.c,3,3,'A');w=core.add_subshot(self.c,3,3,'B')
        self.add(3,'S','B',sub=u)
        self.add(3,'R','S',sub=w)
        core.add_media(self.c,3,2,self.media('single.wav'),'audio')
        self.add(1,scene=4)
        before=copy.deepcopy(self.c)
        rows=lib.select_rows(self.c,[3])
        self.assertEqual([r['category'] for r in rows],[1,2,3,1,1,4,3,1])
        self.assertTrue(rows[3]['promoted'])
        self.assertTrue(rows[6]['only_reject'])
        self.assertEqual(rows[0]['audio']['quality'],'S')
        self.assertEqual(self.c,before)

    def test_review_and_stale(self):
        self.add(1,state='REVIEW')
        t=self.add(2)
        t['sync']['signature']=None
        self.add(3,state='KO')
        rows=lib.select_rows(self.c,[3])
        self.assertEqual([r['category'] for r in rows],[5,5,5])
        self.assertEqual([r['status'] for r in rows],['REVIEW','PENDING','KO'])

    def test_package_identity_originals_and_report(self):
        t=self.add(1,offset=-6.939585)
        self.add(2,video=Path(t['video']['path']),offset=.138,method='manual')
        self.add(3,state='REVIEW')
        before=copy.deepcopy(self.c)
        with patch.object(lib,'probe',side_effect=self.probe):
            dest,n,_=lib.export_library(self.c,self.base,[3],'it',ffprobe='mock')
        self.assertEqual(n,3)
        m=json.loads((dest/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(set(r['id'] for r in m['rows'])),3)
        self.assertEqual(m['rows'][0]['video']['path'],m['rows'][1]['video']['path'])
        self.assertNotEqual(m['rows'][0]['video']['alias'],m['rows'][1]['video']['alias'])
        self.assertEqual(m['rows'][0]['offset'],-6.939585)
        self.assertEqual(m['rows'][1]['method'],'manual')
        root=E.parse(dest/'library_mam.xml')
        clips=root.findall('.//clip')
        self.assertEqual(len(clips),11) # 6 occurrences + 5 unique originals
        self.assertEqual(len({n.attrib['id'] for n in clips}),len(clips))
        self.assertEqual(len(root.findall('.//bin[not(children/*)]')) if False else
                         sum(not len(n.find('children')) for n in root.findall('.//bin')),0)
        self.assertTrue(all(x.text.startswith('file:') for x in root.findall('.//pathurl')))
        self.assertEqual(root.find('.//file/timecode/string').text,'05:25:20:12')
        self.assertTrue((dest/'sync_library.lua').is_file())
        self.assertEqual(self.c,before)

    def test_missing_source_and_timecode(self):
        self.add(1)
        with patch.object(lib,'probe',side_effect=ValueError('bad source')):
            dest,n,w=lib.export_library(self.c,self.base,[3],ffprobe='mock')
        self.assertTrue(w)
        m=json.loads((dest/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(m['rows'][0]['category'],5)
        self.assertEqual(m['rows'][0]['status'],'PENDING')
        self.assertEqual(lib.tc_frames('05:25:20:12',Fraction(25)),488012)
        self.assertEqual(lib.tc_frames('00:01:00;02',Fraction(30000,1001)),1800)
        self.assertIsNone(lib.tc_frames('00:01:00;00',Fraction(30000,1001)))

    @unittest.skipUnless(shutil.which('lua5.4') or shutil.which('lua'),'Lua interpreter for mock API test')
    def test_internal_lua_simulation_and_repeat(self):
        for h,lag,method in [(1,-6.939585,'waveform'),(2,.138,'manual'),(3,0.,'manual')]:
            self.add(h,offset=lag,method=method)
        with patch.object(lib,'probe',side_effect=self.probe):
            dest,_,_=lib.export_library(self.c,self.base,[3],ffprobe='mock')
        m=json.loads((dest/'manifest.json').read_text(encoding='utf-8'))
        driver='local manifest = '+lib.lua_literal(m)+'\n'+MOCK_LUA
        script=dest/'driver.lua';script.write_text(driver,encoding='utf-8')
        p=subprocess.run([shutil.which('lua5.4') or shutil.which('lua'),str(script),str(dest/'sync_library.lua')],
            capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        report=(dest/'sync_report.tsv').read_text(encoding='utf-8')
        self.assertIn('OK_WAVEFORM',report)
        self.assertEqual(report.count('\tOK_MARKER\t'),2)
        self.assertEqual(report.count('\tSKIP_JOURNAL\t'),3)

MOCK_LUA=r'''
local counter=0
local function newFolder(name)
    local f={name=name,folders={},clips={}}
    function f:GetName() return self.name end
    function f:GetClipList() return self.clips end
    function f:GetSubFolderList() return self.folders end
    return f
end
local function addFolder(parent,name)
    local f=newFolder(name);table.insert(parent.folders,f);return f
end
local function find(parent,name)
    for _,f in ipairs(parent.folders) do if f.name==name then return f end end
    return addFolder(parent,name)
end
local root=newFolder("Master")
local pkg=addFolder(root,manifest.root)
local function item(m)
    counter=counter+1
    local i={uid=tostring(counter),marks={},props={
        ["File Path"]=m.path,["Clip Name"]=m.alias,["FPS"]="25",["Frames"]="960",
        ["Audio Ch"]=tostring(m.channels),["Synced Audio"]="",["Audio Offset"]="0",
        ["Start TC"]=m.timecode or ""}}
    function i:GetUniqueId() return self.uid end
    function i:GetName() return self.props["Clip Name"] end
    function i:GetClipProperty(k) return self.props[k] or "" end
    function i:SetClipProperty(k,v) self.props[k]=v;return true end
    function i:SetMetadata(k,v) return true end
    function i:SetClipColor(c) return true end
    function i:GetMarkers() return self.marks end
    function i:AddMarker(f,c,n,nt,d,cd) self.marks[f]={customData=cd};return true end
    function i:DeleteMarkerAtFrame(f) self.marks[f]=nil;return true end
    return i
end
for _,row in ipairs(manifest.rows) do
    local f=pkg
    for j=2,#row.bins do f=find(f,row.bins[j]) end
    local v,a=item(row.video),item(row.audio)
    v.row=row
    table.insert(f.clips,v);table.insert(f.clips,a)
end
local pool={calls=0}
function pool:GetRootFolder() return root end
function pool:GetUniqueId() return "pool-1" end
function pool:GetCurrentFolder() return root end
function pool:SetCurrentFolder(f) return true end
function pool:AutoSyncAudio(items,st)
    self.calls=self.calls+1
    assert(st[3]==true and st[4]==true and st[2]==1,"settings")
    local v,a=items[1],items[2]
    assert(v.props["Synced Audio"]=="","duplicate attachment")
    local lag
    if st[1]==10 then
        assert(v.row.method~="manual","manual must not waveform")
        lag=-173.75
    else
        local vi,ai=next(v.marks),next(a.marks)
        assert(vi and ai,"marker missing")
        lag=ai-vi
    end
    v.props["Synced Audio"]=a:GetName()
    v.props["Audio Offset"]=tostring(lag)
    v.props["Audio Ch"]="3"
    return true
end
local project={}
function project:GetMediaPool() return pool end
function project:GetUniqueId() return "project-1" end
local manager={}
function manager:GetCurrentProject() return project end
resolve={AUDIO_SYNC_MODE=1,AUDIO_SYNC_CHANNEL_NUMBER=2,AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO=3,
         AUDIO_SYNC_RETAIN_VIDEO_METADATA=4,AUDIO_SYNC_WAVEFORM=10,AUDIO_SYNC_MARKER=11}
function resolve:GetProjectManager() return manager end
dofile(arg[1]);assert(pool.calls==3,"first run should sync three pairs")
dofile(arg[1]);assert(pool.calls==3,"rerun must not sync again")
'''
