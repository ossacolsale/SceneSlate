"""Experimental Resolve MAM library. No Resolve process/API is used by Python."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as E

import scene_core as core
import scene_sync as sync
from scene_resolve_lua import LUA

APP_VERSION='3.12.0-experimental.1'
CATEGORIES={1:('01 – Selezione','01 – Selection'),2:('02 – Alternative','02 – Alternatives'),
            3:('03 – Scarti','03 – Rejects'),4:('04 – Audio singoli','04 – Audio only'),
            5:('05 – Da verificare','05 – To review')}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
                      separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()

def select_rows(c, scenes=None):
    """Classify per direct shot or sub-shot, never by audio rating."""
    selected=None if scenes is None else set(scenes)
    rows=[]
    for scene,shot,sub,container in core.iter_containers(c):
        if selected is not None and scene['number'] not in selected:continue
        good=any(t.get('video') and t['video']['quality']=='B' for t in container['takes'])
        for t in sorted(container['takes'],key=lambda t:t['number']):
            v,a=t.get('video'),t.get('audio')
            if not (v or a):continue
            category=4 if not v else 1 if v['quality']=='B' or (v['quality']=='R' and not good) else 2 if v['quality']=='R' else 3
            ref=[scene['number'],shot['number'],sub['id'] if sub else '',t['number']]
            ident=digest(ref)[:20]
            status=sync.effective_status(t)
            raw=t.get('sync') or {}
            offset=raw.get('offset_seconds')
            usable=isinstance(offset,(float,int)) and not isinstance(offset,bool) and math.isfinite(offset)
            if v and a and (status!='OK' or not usable):
                status=status if status!='OK' else 'PENDING'
            rows.append(dict(id=ident,scene=scene['number'],shot=shot['number'],
                subshot=sub['name'] if sub else '',subshot_id=ref[2],take=t['number'],
                category=5 if v and a and status!='OK' else category,quality_category=category,
                promoted=bool(v and v['quality']=='R' and category==1),
                status=status,stored_status=raw.get('status'),offset=offset if usable else None,
                method=raw.get('method',''),video=v and dict(v),audio=a and dict(a),
                descriptions=[scene.get('description',''),shot.get('description',''),
                              sub.get('description','') if sub else '',t.get('description',''),t.get('annotation','')],
                only_reject=bool(v and all(not x.get('video') or x['video']['quality']=='S' for x in container['takes']))))
    return rows

def fraction(value):
    try:
        f=Fraction(str(value))
        return f if f>0 else None
    except (ValueError,TypeError,ZeroDivisionError):return None

def probe(path, exe):
    p=subprocess.run([exe,'-v','error','-show_streams','-show_format','-of','json',str(path)],
        capture_output=True,encoding='utf-8',errors='replace',timeout=40)
    if p.returncode:raise ValueError((p.stderr or 'FFprobe error')[:400])
    data=json.loads(p.stdout)
    streams=data.get('streams',[]);fmt=data.get('format',{})
    v=next((x for x in streams if x.get('codec_type')=='video' and not x.get('disposition',{}).get('attached_pic')),None)
    audio=[x for x in streams if x.get('codec_type')=='audio']
    dur=fraction((v or (audio[0] if audio else {})).get('duration')) or fraction(fmt.get('duration'))
    if not dur:raise ValueError('duration unavailable')
    fps=fraction(v.get('avg_frame_rate')) if v else None
    if v and not fps:raise ValueError('source FPS unavailable')
    tc_tags=[str(x.get('tags',{}).get('timecode','')) for x in ([v] if v else [])+streams+[fmt]]
    tc=next((x for x in tc_tags if x),'')
    return dict(path=str(Path(path).resolve()),duration=float(dur),fps=str(fps) if fps else None,
                timecode=tc,video=v,audio=audio,raw=data)

def tc_frames(tc, fps):
    """SMPTE source TC including 29.97/59.94 DF; return None if unknown."""
    if not tc:return None
    m=re.fullmatch(r'(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})',tc)
    if not m:return None
    h,mi,s,f=int(m[1]),int(m[2]),int(m[3]),int(m[5]);nom=round(fps)
    if h>=24 or mi>=60 or s>=60 or f>=nom:return None
    frames=((h*60+mi)*60+s)*nom+f
    if m[4]==';':
        if fps not in (Fraction(30000,1001),Fraction(60000,1001)):return None
        drop=2 if nom==30 else 4
        if mi%10 and s==0 and f<drop:return None
        frames-=drop*(h*60+mi-(h*60+mi)//10)
    return frames

def x(parent,tag,value=None,**attrs):
    n=E.SubElement(parent,tag,attrs)
    if value is not None:n.text=str(value)
    return n

def rate(p,fps):
    rr=x(p,'rate');x(rr,'timebase',round(fps))
    x(rr,'ntsc','TRUE' if fps in (Fraction(24000,1001),Fraction(30000,1001),Fraction(60000,1001)) else 'FALSE')

def timecode(p,m,fps):
    frames=tc_frames(m['timecode'],fps)
    if frames is None:return
    t=x(p,'timecode');rate(t,fps);x(t,'string',m['timecode']);x(t,'frame',frames)
    x(t,'displayformat','DF' if ';' in m['timecode'] else 'NDF')

def file_node(p,m,ident,fps):
    f=x(p,'file',id=ident);x(f,'name',Path(m['path']).name)
    x(f,'pathurl',Path(m['path']).as_uri());rate(f,fps)
    x(f,'duration',max(1,round(m['duration']*fps)));timecode(f,m,fps)
    media=x(f,'media')
    if m['video']:
        v=x(x(media,'video'),'samplecharacteristics');rate(v,fps)
        x(v,'width',m['video']['width']);x(v,'height',m['video']['height'])
    if m['audio']:
        a=x(media,'audio');sc=x(a,'samplecharacteristics');first=m['audio'][0]
        if first.get('bits_per_raw_sample') or first.get('bits_per_sample'):
            depth=first.get('bits_per_raw_sample') or first.get('bits_per_sample')
            if str(depth).isdigit() and int(depth)>0:x(sc,'depth',depth)
        if first.get('sample_rate'):x(sc,'samplerate',first['sample_rate'])
        x(a,'channelcount',sum(int(i.get('channels',0)) for i in m['audio']))
    return f

def mam_clip(p,m,ident,name,comments):
    # Audio-only XML uses 25 as interchange timebase, not an assertion about
    # the marker coordinate system of an audio-only MediaPoolItem.
    fps=Fraction(m['fps']) if m['fps'] else Fraction(25)
    cl=x(p,'clip',id=ident);x(cl,'name',name);x(cl,'ismasterclip','TRUE')
    x(cl,'masterclipid',ident);rate(cl,fps);x(cl,'duration',max(1,round(m['duration']*fps)))
    timecode(cl,m,fps);logging=x(cl,'logginginfo');x(logging,'lognote',comments)
    media=x(cl,'media');first=True
    for kind,n in [('video',int(bool(m['video']))),('audio',sum(int(a.get('channels',0)) for a in m['audio']))]:
        if not n:continue
        parent=x(media,kind)
        for ch in range(1,n+1):
            ci=x(x(parent,'track'),'clipitem',id=f'{ident}-{kind}-{ch}')
            x(ci,'name',name);x(ci,'masterclipid',ident);rate(ci,fps)
            x(ci,'duration',max(1,round(m['duration']*fps)))
            if first:file_node(ci,m,ident+'-file',fps);first=False
            else:x(ci,'file',id=ident+'-file')
            if kind=='audio':
                st=x(ci,'sourcetrack');x(st,'mediatype','audio');x(st,'trackindex',ch)

def lua_literal(v):
    # Quoted UTF-8 bytes with exact three-digit decimal escapes for controls.
    if v is None:return 'nil'
    if v is True:return 'true'
    if v is False:return 'false'
    if isinstance(v,str):
        return '"'+''.join('\\%03d'%ord(c) if ord(c)<32 or ord(c)==127 else '\\'+c if c in '\\\"' else c for c in v)+'"'
    if isinstance(v,(int,float)):
        if not math.isfinite(v):raise ValueError('non-finite manifest number')
        return repr(v)
    if isinstance(v,list):return '{'+','.join(lua_literal(i) for i in v)+'}'
    if isinstance(v,dict):return '{'+','.join('['+lua_literal(k)+']='+lua_literal(i) for k,i in v.items())+'}'
    raise TypeError(type(v).__name__)

def export_library(c,directory,scenes=None,language='en',ffprobe=None):
    """Create one new package, even when exporting the same catalog again."""
    rows=select_rows(c,scenes)
    if not rows:raise core.CatalogError('No takes in selected scenes.')
    exe=ffprobe or sync.executables()[1]
    if not exe:raise core.CatalogError('FFprobe is required for Resolve library export.')
    issues=[];omissions=[];cache={}
    for row in rows:
        for kind in ('video','audio'):
            med=row[kind]
            if not med:continue
            key=core.identity(med['path'])
            if key not in cache:
                try:cache[key]=probe(med['path'],exe)
                except (OSError,ValueError,subprocess.SubprocessError) as err:
                    cache[key]=None;issues.append(f'{med["path"]}: {err}')
            m=cache[key]
            if not m or (kind=='video' and not m['video']) or (kind=='audio' and not m['audio']):
                med['available']=False
                row['category']=5;row['status']='PENDING'
                issues.append(f'{row["id"]}: unavailable {kind} source {med["path"]}')
                continue
            med.update(available=True,path=m['path'],fps=m['fps'],duration=m['duration'],
                       timecode=m['timecode'],channels=sum(int(a.get('channels',0)) for a in m['audio']))
            if m['video'] and tc_frames(m['timecode'],Fraction(m['fps'])) is None:
                omissions.append(f'{m["path"]}: no usable source timecode; Resolve reads original media.')
        if row['video'] and row['audio'] and row['status']=='OK':
            v,a=row['video'],row['audio'];lag=row['offset']
            if min(v.get('duration',0),a.get('duration',0)-lag)<=max(0.,-lag):
                row['status']='PENDING';row['category']=5;issues.append(f'{row["id"]}: no valid overlap')
    lang=0 if language=='it' else 1
    repetitions=Counter((row['scene'],row['shot'],row['subshot_id'],row['category'],kind,core.identity(row[kind]['path']))
        for row in rows for kind in ('video','audio') if row[kind] and row[kind].get('available'))
    # Stable ID includes source fingerprints and placement. Distinct packages never
    # overwrite an existing project bin; repeated execution of one package is audited.
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    root_name='SceneSlate 3.12 – '+stamp
    dest=Path(directory)/('Resolve_Library_'+stamp)
    dest.mkdir(parents=True,exist_ok=False)
    root=E.Element('xmeml',version='5');project=x(root,'project');x(project,'name',root_name)
    top=x(project,'children');bins={};originals=set()
    def bin_for(names):
        parent=top;key=()
        for name in names:
            key+=(name,)
            if key not in bins:
                b=x(parent,'bin');x(b,'name',name);bins[key]=x(b,'children')
            parent=bins[key]
        return parent
    for row in rows:
        label=f'S{row["scene"]:03d} SH{row["shot"]:03d}'
        if row['subshot']:label+=' '+row['subshot']
        label+=f' T{row["take"]:03d}'
        v,a=row['video'],row['audio']
        q={'B':'G','R':'R','S':'X'} if lang==1 else {'B':'B','R':'R','S':'S'}
        label+=f' V-{q[v["quality"]] if v else "-"} A-{q[a["quality"]] if a else "-"}'
        row['label']=label
        shot=f'Shot {row["shot"]:03d}'
        if row['subshot']:shot+=' – '+row['subshot']
        # A shot/sub-shot pair with a similar display name remains identifiable by token.
        names=[root_name,f'Scena {row["scene"]:03d}' if lang==0 else f'Scene {row["scene"]:03d}',CATEGORIES[row['category']][lang],shot]
        if any(repetitions[(row['scene'],row['shot'],row['subshot_id'],row['category'],kind,core.identity(row[kind]['path']))]>1
               for kind in ('video','audio') if row[kind] and row[kind].get('available')):
            names.append(f'Take {row["take"]:03d} – {row["id"][:8]}')
        row['bins']=names
        for kind in ('video','audio'):
            med=row[kind]
            if not med or not med.get('available'):continue
            m=cache[core.identity(med['path'])]
            ident='ss-'+row['id']+'-'+kind
            med['alias']=label+' ['+ident+']'
            med['original_name']=Path(med['path']).name
            comments=' | '.join([ident,med['path'],*filter(None,row['descriptions']),med.get('notes','')])
            mam_clip(bin_for(names),m,ident,med['alias'],comments)
            okey=(kind,core.identity(med['path']))
            if okey not in originals:
                originals.add(okey)
                mam_clip(bin_for([root_name,'00 – Originali' if lang==0 else '00 – Originals',kind.upper()]),
                    m,'orig-'+digest(okey)[:20],med['original_name'],med['path'])
    E.indent(root,space='  ');E.ElementTree(root).write(dest/'library_mam.xml',encoding='utf-8',xml_declaration=True)
    manifest={'version':APP_VERSION,'root':root_name,'rows':rows,'language':language,
              'timeline_fps':25,'timeline_resolution':[1920,1080]}
    (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (dest/'sync_library.lua').write_text('local manifest = '+lua_literal(manifest)+'\n'+LUA,encoding='utf-8')
    (dest/'ffprobe.json').write_text(json.dumps({k:v['raw'] if v else None for k,v in cache.items()},ensure_ascii=False,indent=2),encoding='utf-8')
    counts=Counter(r['category'] for r in rows)
    report=[f'SceneSlate {APP_VERSION} — Resolve library',f'Takes: {len(rows)}',
        *[f'{CATEGORIES[k][lang]}: {n}' for k,n in sorted(counts.items())],
        '', 'Rejected-only angles: '+', '.join(sorted(set(r['label'].split(' T')[0] for r in rows if r['only_reject']))),
        '', 'EXPORT ERRORS:',*issues,'','METADATA OMISSIONS (not export failures):',*dict.fromkeys(omissions),
        '', 'Validated in report 08: waveform + marker, sign and units at 25 fps, reimported distinct IDs, Source Viewer/F9. Pending: full scene, positive offsets, mixed rates, fallback quarantine, repeat execution.',
        'No physical media copied; catalog unchanged.']
    (dest/'export_report.txt').write_text('\n'.join(report)+'\n',encoding='utf-8')
    (dest/'LEGGIMI_README.txt').write_text(INSTRUCTIONS,encoding='utf-8')
    return dest,len(rows),issues+omissions

INSTRUCTIONS="""SceneSlate 3.12.0 — EXPERIMENTAL / SPERIMENTALE
IT: usa una COPIA del progetto temporaneo. Importa library_mam.xml dal menu Media Pool
Import Media from XML (non come timeline). Non reimportare lo stesso XML due volte.
Apri Workspace > Console, seleziona Lua, esegui:
    dofile([[PERCORSO COMPLETO\\sync_library.lua]])
Esecuzione: lo script sincronizza nel progetto di prova. Leggi sync_report.tsv.
Imposta APPLY=false all'inizio dello script per una verifica di sola lettura.
Collaudo 08: segno coincidente, offset in fotogrammi a 25 fps, marker video 174/WAV 0.
Per una waveform fuori tolleranza lo script conserva il tentativo in Sync diagnostics
e prova a reimportare un MediaPoolItem distinto, quindi applica marker.
Il percorso di fallback completo e i marker positivi restano da collaudare.
Per verificare le tracce usa Clip Attributes, Source Viewer, In/Out, F9/F10.
Non modificare o cancellare sync_state.tsv: e' il registro di tentativi di questo pacchetto.
EN: use a COPY of the temporary project. Import library_mam.xml via Media Pool
Import Media from XML, not timeline import. Import only once. In Workspace > Console
select Lua and use dofile([[FULL PATH\\sync_library.lua]]).
Default APPLY synchronizes within the test project. Set APPLY=false for read-only audit.
Report 08 confirms same offset sign and frame units at 25 fps, marker sync, distinct
reimported IDs, and Source Viewer editing. An unacceptable attached waveform is
quarantined; a separately imported item is used for marker fallback. Verify this
fallback and positive offsets in the real project.
Verify Clip Attributes, Source Viewer, In/Out, F9/F10. Keep sync_state.tsv.
All original media and the catalog remain untouched.
"""
