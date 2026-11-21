"""SceneSlate 3.1 catalog engine: scene/shot/subshot/take with video/audio pairs.

No media file is modified. This module has no GUI dependencies.
"""
from __future__ import annotations

import copy
import csv
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
from collections import defaultdict
from uuid import uuid4

VERSION = 4
QUALITIES = {'B': 'Buona', 'R': 'Riserva', 'S': 'Scarto'}
VIDEO_EXT = {'.mov','.mp4','.mxf','.avi','.mkv','.mts','.m2ts','.mpg','.mpeg','.wmv','.webm','.r3d','.braw','.mp4v','.m4v'}
AUDIO_EXT = {'.wav','.bwf','.mp3','.flac','.aif','.aiff','.m4a','.ogg','.wma','.caf'}

class CatalogError(ValueError):
    pass


def new_catalog():
    return {'version': VERSION, 'name': 'Nuovo catalogo',
            'settings': {'scene_label': 'Scena', 'shot_label': 'Shot', 'separator': ' / ', 'padding': 0},
            'video_root': '', 'audio_root': '', 'scenes': []}


def positive_number(value):
    try: number = int(str(value).strip())
    except (TypeError, ValueError): raise CatalogError('Il numero deve essere un intero positivo.') from None
    if number < 1 or str(value).strip() not in (str(number), f'+{number}'):
        raise CatalogError('Usa numeri naturali maggiori di zero (1, 2, 3...).')
    return number


def scene_for(c, number):
    return next((s for s in c['scenes'] if s['number'] == number), None)


def shot_for(c, scene_number, shot_number):
    scene = scene_for(c, scene_number)
    return next((sh for sh in scene['shots'] if sh['number'] == shot_number), None) if scene else None


def take_for(c, scene_number, shot_number, take_number, subshot_id=None):
    container = container_for(c, scene_number, shot_number, subshot_id)
    return next((t for t in container['takes'] if t['number'] == take_number), None) if container else None


def next_number(entries):
    return max((item['number'] for item in entries), default=0) + 1


def add_scene(c, number=None):
    number = positive_number(number) if number is not None else next_number(c['scenes'])
    if scene_for(c, number): raise CatalogError(f'La scena {number} esiste già.')
    c['scenes'].append({'number': number, 'description': '', 'notes': '', 'shots': []})
    c['scenes'].sort(key=lambda s:s['number'])
    return number


def rename_scene(c, old, new):
    scene = scene_for(c, old)
    if scene is None: raise CatalogError('Scena non trovata.')
    new = positive_number(new)
    if new != old and scene_for(c, new): raise CatalogError(f'La scena {new} esiste già.')
    scene['number'] = new; c['scenes'].sort(key=lambda s:s['number'])


def remove_scene(c, number):
    scene = scene_for(c, number)
    if scene is None: raise CatalogError('Scena non trovata.')
    c['scenes'].remove(scene)


def add_shot(c, scene_number, number=None):
    scene = scene_for(c, scene_number)
    if scene is None: raise CatalogError('Seleziona una scena.')
    number = positive_number(number) if number is not None else next_number(scene['shots'])
    if shot_for(c, scene_number, number): raise CatalogError(f'Lo shot {number} esiste già.')
    scene['shots'].append({'number':number,'description':'','notes':'','takes':[],'subshots':[]})
    scene['shots'].sort(key=lambda x:x['number'])
    return number


def rename_shot(c, scene_number, old, new):
    shot = shot_for(c, scene_number, old)
    if shot is None: raise CatalogError('Shot non trovato.')
    new = positive_number(new)
    if new != old and shot_for(c, scene_number, new): raise CatalogError(f'Lo shot {new} esiste già.')
    shot['number'] = new
    scene_for(c, scene_number)['shots'].sort(key=lambda x:x['number'])


def remove_shot(c, scene_number, number):
    scene = scene_for(c, scene_number)
    shot = shot_for(c, scene_number, number)
    if shot is None: raise CatalogError('Shot non trovato.')
    scene['shots'].remove(shot)



def subshot_for(c, scene_number, shot_number, subshot_id):
    sh = shot_for(c, scene_number, shot_number)
    return next((u for u in sh.get('subshots', []) if u['id'] == subshot_id), None) if sh else None


def container_for(c, scene_number, shot_number, subshot_id=None):
    return (subshot_for(c, scene_number, shot_number, subshot_id) if subshot_id is not None
            else shot_for(c, scene_number, shot_number))


def clean_subshot_name(name):
    if not isinstance(name, str) or not name.strip():
        raise CatalogError('Il nome del sotto-shot non può essere vuoto.')
    if len(name.strip()) > 100:
        raise CatalogError('Il nome del sotto-shot è troppo lungo (massimo 100 caratteri).')
    return name.strip()


def unique_subshot_name(shot, name):
    names = {u['name'].casefold() for u in shot.get('subshots', [])}
    if name.casefold() not in names:
        return name
    n = 2
    while f'{name} (copia {n})'.casefold() in names:
        n += 1
    return f'{name} (copia {n})'


def add_subshot(c, scene_number, shot_number, name):
    shot = shot_for(c, scene_number, shot_number)
    if shot is None:
        raise CatalogError('Seleziona prima uno shot.')
    name = clean_subshot_name(name)
    if any(u['name'].casefold() == name.casefold() for u in shot.get('subshots', [])):
        raise CatalogError(f'Sotto-shot {name} già presente nello shot.')
    item = {'id': uuid4().hex, 'name': name, 'description': '', 'notes': '', 'takes': []}
    shot.setdefault('subshots', []).append(item)
    return item['id']


def rename_subshot(c, scene_number, shot_number, subshot_id, name):
    item = subshot_for(c, scene_number, shot_number, subshot_id)
    if item is None:
        raise CatalogError('Sotto-shot non trovato.')
    name = clean_subshot_name(name)
    shot = shot_for(c, scene_number, shot_number)
    if any(u['id'] != subshot_id and u['name'].casefold() == name.casefold() for u in shot['subshots']):
        raise CatalogError(f'Sotto-shot {name} già presente nello shot.')
    item['name'] = name


def remove_subshot(c, scene_number, shot_number, subshot_id):
    shot = shot_for(c, scene_number, shot_number)
    item = subshot_for(c, scene_number, shot_number, subshot_id)
    if item is None:
        raise CatalogError('Sotto-shot non trovato.')
    shot['subshots'].remove(item)


def iter_containers(c):
    """(scene, shot, subshot or None, container) in display order."""
    for scene in sorted(c['scenes'], key=lambda s: s['number']):
        for shot in sorted(scene['shots'], key=lambda sh: sh['number']):
            yield scene, shot, None, shot
            for sub in shot.get('subshots', []):
                yield scene, shot, sub, sub


def iter_media_context(c):
    """(scene, shot, subshot or None, take, kind, media)."""
    for scene, shot, sub, container in iter_containers(c):
        for take in sorted(container['takes'], key=lambda t: t['number']):
            for kind in ('video', 'audio'):
                if take.get(kind):
                    yield scene, shot, sub, take, kind, take[kind]

def canonical(path):
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def identity(path):
    return os.path.normcase(canonical(path))


def media_info(path, quality='B'):
    if quality not in QUALITIES: raise CatalogError('Qualità non valida.')
    path = canonical(path)
    if not Path(path).is_file(): raise CatalogError(f'File non trovato: {path}')
    return {'path':path,'quality':quality,'notes':''}


def birth_timestamp(stat_info, platform=None):
    platform = sys.platform if platform is None else platform
    birth = getattr(stat_info, 'st_birthtime', None)
    if birth is not None:return float(birth), True
    if platform == 'win32':return float(stat_info.st_ctime), True
    return float(stat_info.st_mtime), False


def take_time(take):
    """Earliest available file date, never parsed from filename. Files may lack birthtime."""
    dates=[]
    for kind in ('video','audio'):
        med=take.get(kind)
        if med:
            try: dates.append(birth_timestamp(Path(med['path']).stat())[0])
            except OSError: pass
    return min(dates) if dates else float('inf')


def renumber_auto_takes(container):
    """Recalculate unlocked take numbers in original insertion order.

    This operation is intentionally EXPLICIT (manual number change or 'Auto');
    adding a new pair never reorders existing takes based on filesystem dates.
    """
    locked = {t['number'] for t in container['takes'] if t.get('manual_number')}
    autos = sorted((t for t in container['takes'] if not t.get('manual_number')),
                   key=lambda t: t['order'])
    next_free = 1
    for t in autos:
        while next_free in locked:
            next_free += 1
        t['number'] = next_free
        next_free += 1
    container['takes'].sort(key=lambda t: t['number'])


def add_take(c, scene_number, shot_number, number=None, subshot_id=None):
    container = container_for(c, scene_number, shot_number, subshot_id)
    if container is None:
        raise CatalogError('Seleziona uno shot o sotto-shot.')
    used = {t['number'] for t in container['takes']}
    next_auto = max(used, default=0) + 1
    number = next_auto if number is None else positive_number(number)
    if number in used:
        raise CatalogError(f'Ciak {number} già presente.')
    order = max((t.get('order', 0) for t in container['takes']), default=0) + 1
    take = {'number': number, 'manual_number': number != next_auto,
            'order': order, 'video': None, 'audio': None,
            'description': '', 'annotation': '', 'notes': ''}
    container['takes'].append(take)
    container['takes'].sort(key=lambda t: t['number'])
    return take


def set_take_number(c,scene_number,shot_number,old,new,subshot_id=None):
    take=take_for(c,scene_number,shot_number,old,subshot_id)
    if take is None:raise CatalogError('Ciak non trovato.')
    new=positive_number(new)
    occupied=take_for(c,scene_number,shot_number,new,subshot_id) if new!=old else None
    if occupied and occupied.get('manual_number',False):
        raise CatalogError(f'Ciak {new} già fissato manualmente.')
    # When occupied by an automatically numbered take, the automatic one shifts.
    # This makes manual renumbering ergonomic even when there are no gaps.
    take['number']=new; take['manual_number']=True
    renumber_auto_takes(container_for(c,scene_number,shot_number,subshot_id))
    return take['number']


def reset_take_auto(c,scene_number,shot_number,number,subshot_id=None):
    take=take_for(c,scene_number,shot_number,number,subshot_id)
    if take is None:raise CatalogError('Ciak non trovato.')
    take['manual_number']=False
    renumber_auto_takes(container_for(c,scene_number,shot_number,subshot_id))
    return take['number']


def remove_take(c,scene_number,shot_number,number,subshot_id=None):
    sh=container_for(c,scene_number,shot_number,subshot_id)
    t=take_for(c,scene_number,shot_number,number,subshot_id)
    if t is None:raise CatalogError('Ciak non trovato.')
    sh['takes'].remove(t)
    # Deleting a ciak does not unexpectedly renumber all subsequent ones.


def add_media(c,scene_number,shot_number,path,kind,quality='B',take_number=None,subshot_id=None):
    """Explicit pairing: specify take_number to fill a side; without it create a new row.

    Returns (take, changed). Never silently pairs media just by date.
    """
    if kind not in ('video','audio'):raise CatalogError('Tipo file non valido.')
    sh=container_for(c,scene_number,shot_number,subshot_id)
    if sh is None:raise CatalogError('Seleziona uno shot o sotto-shot prima di associare file.')
    info=media_info(path,quality)
    if any(t[kind] and identity(t[kind]['path'])==identity(info['path']) for t in sh['takes']):
        return (None,False)
    target=take_for(c,scene_number,shot_number,take_number,subshot_id) if take_number is not None else None
    if take_number is not None and target is None:raise CatalogError('Ciak di destinazione non trovato.')
    if target is not None and target[kind] is not None:
        raise CatalogError(f'Ciak {target["number"]}: lato {kind} già occupato. Usa un nuovo ciak oppure rimuovi il lato.')
    if target is None:target=add_take(c,scene_number,shot_number,subshot_id=subshot_id)
    target[kind]=info
    return (target,True)


def remove_media(c,scene_number,shot_number,take_number,kind,subshot_id=None):
    take=take_for(c,scene_number,shot_number,take_number,subshot_id)
    if take is None:raise CatalogError('Ciak non trovato.')
    if kind not in ('video','audio'):raise CatalogError('Lato non valido.')
    take[kind]=None
    sh=container_for(c,scene_number,shot_number,subshot_id)
    if not take['video'] and not take['audio']:sh['takes'].remove(take)
    # No implicit renumbering after removing a media reference.


def label(c,scene_number,shot_number=None,subshot_name=None):
    st=c['settings'];pad=int(st.get('padding',0))
    fmt=lambda x:str(x).zfill(pad)
    out=f"{st['scene_label']} {fmt(scene_number)}"
    if shot_number is not None:out+=f"{st['separator']}{st['shot_label']} {fmt(shot_number)}"
    if subshot_name is not None:out+=f" / {subshot_name}"
    return out


def iter_media(c):
    """Legacy-compatible iterator (scene, shot, take, kind, media)."""
    for scene, shot, _subshot, take, kind, media in iter_media_context(c):
        yield scene, shot, take, kind, media


def validate(c):
    if not isinstance(c, dict) or c.get('version') != VERSION:
        raise CatalogError('Versione del catalogo non riconosciuta.')
    if not isinstance(c.get('scenes'), list):
        raise CatalogError('Catalogo danneggiato: scenes.')
    def validate_takes(container, prefix):
        nums, orders = set(), set()
        if not isinstance(container.get('takes'), list):
            raise CatalogError(f'Ciak non validi in {prefix}')
        for take in container['takes']:
            tn = positive_number(take['number'])
            if tn in nums:
                raise CatalogError(f'Ciak duplicato: {prefix}/{tn}')
            nums.add(tn)
            order = positive_number(take.get('order'))
            if order in orders: raise CatalogError(f'Ordine ciak duplicato: {prefix}/{order}')
            orders.add(order)
            if not isinstance(take.get('description'), str) or not isinstance(take.get('annotation'), str):
                raise CatalogError(f'Descrizione/annotazione non valida nel ciak {prefix}/{tn}')
            if type(take.get('manual_number')) is not bool:
                raise CatalogError('Flag ciak manuale non valido.')
            for kind in ('video', 'audio'):
                med = take.get(kind)
                if med is not None and (not isinstance(med, dict) or med.get('quality') not in QUALITIES or not isinstance(med.get('path'), str)):
                    raise CatalogError(f'File {kind} non valido in {prefix}/{tn}')
            if take.get('video') is None and take.get('audio') is None:
                raise CatalogError(f'Ciak {prefix}/{tn} senza file.')
    scene_nums = set()
    for scene in c['scenes']:
        n = positive_number(scene['number'])
        if not isinstance(scene.get('description'),str):raise CatalogError('Descrizione scena non valida.')
        if n in scene_nums:raise CatalogError(f'Scena duplicata: {n}')
        scene_nums.add(n)
        shot_nums = set()
        for shot in scene['shots']:
            sn = positive_number(shot['number'])
            if not isinstance(shot.get('description'),str):raise CatalogError('Descrizione shot non valida.')
            if sn in shot_nums:raise CatalogError(f'Shot duplicato: {n}/{sn}')
            shot_nums.add(sn)
            validate_takes(shot, f'{n}/{sn}')
            if not isinstance(shot.get('subshots'), list):
                raise CatalogError(f'Sotto-shot non validi in {n}/{sn}')
            names, ids = set(), set()
            for sub in shot['subshots']:
                name = clean_subshot_name(sub.get('name'))
                if not isinstance(sub.get('description'),str):raise CatalogError('Descrizione sotto-shot non valida.')
                if not isinstance(sub.get('id'), str) or not sub['id'] or ':' in sub['id']:
                    raise CatalogError('Identificatore sotto-shot non valido.')
                if name.casefold() in names or sub['id'] in ids:
                    raise CatalogError(f'Sotto-shot duplicato in {n}/{sn}: {name}')
                names.add(name.casefold()); ids.add(sub['id'])
                validate_takes(sub, f'{n}/{sn}/{name}')
    st = c.get('settings', {})
    if any(not isinstance(st.get(key), str) for key in ('scene_label','shot_label','separator')):
        raise CatalogError('Convenzione non valida.')
    if not isinstance(st.get('padding'), int) or st['padding'] not in range(7):
        raise CatalogError('Padding non valido (0–6).')
    return True


def migrate_v1(data):
    """Lossless migration: old independent media become separate one-sided takes.

    Old v1 associations carried no reliable pairing information; NEVER infer a pair.
    """
    if data.get('version') != 1:return data
    data=copy.deepcopy(data)
    for scene in data.get('scenes',[]):
        for sh in scene.get('shots',[]):
            old=sh.pop('media',[])
            ordered=sorted(enumerate(old),key=lambda x:(file_time_from_path(x[1].get('path','')),x[0]))
            takes=[]
            for i,(_,m) in enumerate(ordered,1):
                kind=m['kind']; med={k:v for k,v in m.items() if k!='kind'}
                takes.append({'number':i,'manual_number':False,'video':med if kind=='video' else None,
                              'audio':med if kind=='audio' else None,'notes':''})
            sh['takes']=takes
    data['version']=2
    return data



def migrate_legacy(data):
    """Load v1-v3 catalogs non-destructively, without inferring video/audio pairs."""
    if data.get('version') == 1:
        data = migrate_v1(data)
    if data.get('version') in (2, 3):
        data = copy.deepcopy(data)
        for scene in data.get('scenes', []):
            for shot in scene.get('shots', []):
                shot.setdefault('subshots', [])
        data['version'] = 3
    if data.get('version') == 3:
        data = copy.deepcopy(data)
        for scene in data.get('scenes', []):
            scene.setdefault('description', scene.get('notes', ''))
            for shot in scene.get('shots', []):
                shot.setdefault('description', shot.get('notes', ''))
                for sub in shot.get('subshots', []):
                    sub.setdefault('description', sub.get('notes', ''))
                for container in [shot] + shot.get('subshots', []):
                    for index, take in enumerate(container.get('takes', []), 1):
                        take.setdefault('description', '')
                        take.setdefault('annotation', take.get('notes', ''))
                        take.setdefault('order', index)
        data['version'] = VERSION
    return data


def node_snapshot(c, scene_number, shot_number=None, subshot_id=None):
    """An independent value object suitable for repeated paste operations."""
    if subshot_id is not None:
        source = subshot_for(c, scene_number, shot_number, subshot_id)
        kind = 'subshot'
    elif shot_number is not None:
        source = shot_for(c, scene_number, shot_number)
        kind = 'shot'
    else:
        source = scene_for(c, scene_number)
        kind = 'scene'
    if source is None:
        raise CatalogError('Elemento da copiare non trovato.')
    return {'kind': kind, 'data': copy.deepcopy(source)}


def _merge_takes(dst, takes):
    """Append copied rows with new increasing ciak numbers, never duplicate media."""
    next_num = max((t['number'] for t in dst['takes']), default=0)
    next_order = max((t.get('order',0) for t in dst['takes']), default=0)
    for original in takes:
        t = copy.deepcopy(original)
        next_num += 1
        next_order += 1
        t['number'] = next_num
        t['order'] = next_order
        t['manual_number'] = False
        dst['takes'].append(t)
    dst['takes'].sort(key=lambda t: t['number'])


def _append_subshot(shot, item, name=None):
    sub = copy.deepcopy(item)
    sub['id'] = uuid4().hex
    sub['name'] = unique_subshot_name(shot, clean_subshot_name(name if name is not None else sub['name']))
    shot.setdefault('subshots', []).append(sub)
    return sub


def _append_shot(scene, item):
    sh = copy.deepcopy(item)
    existing = {x['number'] for x in scene['shots']}
    if sh['number'] in existing:
        sh['number'] = max(existing, default=0)+1
    for sub in sh.get('subshots', []):
        sub['id'] = uuid4().hex
    scene['shots'].append(sh)
    scene['shots'].sort(key=lambda x: x['number'])
    return sh


def _flatten_takes(data, kind):
    if kind == 'subshot':
        return copy.deepcopy(data['takes'])
    if kind == 'shot':
        containers = [data] + data.get('subshots', [])
    else:
        containers = [item for sh in data['shots'] for item in [sh] + sh.get('subshots', [])]
    return [copy.deepcopy(t) for item in containers for t in item['takes']]


def paste_snapshot(c, snapshot, scene_number, shot_number=None, subshot_id=None):
    """Append without replacing existing content. Supports all source/destination levels.

    Into a scene: scene adds shots, shot adds one shot, subshot adds a shot containing it.
    Into a shot: scene adds subshots labelled by original shot, shot merges takes +
    subshots, subshot adds one subshot. Into a subshot: all sources append takes.
    Every media reference is copied by value (not copied on disk).
    """
    if not isinstance(snapshot, dict) or snapshot.get('kind') not in ('scene','shot','subshot'):
        raise CatalogError('Appunti SceneSlate non validi.')
    kind = snapshot['kind']
    data = copy.deepcopy(snapshot['data'])
    if subshot_id is not None:
        dst = subshot_for(c, scene_number, shot_number, subshot_id)
        if dst is None:raise CatalogError('Sotto-shot di destinazione non trovato.')
        qty = len(_flatten_takes(data, kind))
        _merge_takes(dst, _flatten_takes(data, kind))
        return f'{qty} ciak aggiunti al sotto-shot.'
    if shot_number is not None:
        dst = shot_for(c, scene_number, shot_number)
        if dst is None:raise CatalogError('Shot di destinazione non trovato.')
        if kind == 'subshot':
            _append_subshot(dst, data)
            return 'Sotto-shot aggiunto con tutti i ciak.'
        if kind == 'shot':
            _merge_takes(dst, data['takes'])
            for sub in data.get('subshots', []):_append_subshot(dst, sub)
            return 'Ciak e sotto-shot copiati nello shot.'
        # Paste scene into shot: each original shot becomes one or more subshots.
        for sh in data['shots']:
            if sh['takes']:
                _append_subshot(dst, {'name': f'Shot {sh["number"]}', 'notes': sh.get('notes',''), 'description': sh.get('description',''), 'takes': sh['takes']})
            for sub in sh.get('subshots', []):
                _append_subshot(dst, sub, f'Shot {sh["number"]} · {sub["name"]}')
        return 'Scena inserita come sotto-shot nello shot.'
    dst = scene_for(c, scene_number)
    if dst is None:raise CatalogError('Scena di destinazione non trovata.')
    if kind == 'scene':
        for sh in data['shots']:_append_shot(dst, sh)
        return 'Shot della scena copiati nella scena di destinazione.'
    if kind == 'shot':
        _append_shot(dst, data)
        return 'Shot copiato nella scena di destinazione.'
    shot = _append_shot(dst, {'number': next_number(dst['shots']), 'notes':'', 'description':'', 'takes':[], 'subshots':[]})
    _append_subshot(shot, data)
    return 'Creato un nuovo shot con il sotto-shot copiato.'

def file_time_from_path(path):
    try:return birth_timestamp(Path(path).stat())[0]
    except (OSError,ValueError):return float('inf')


def safe_relative(path,base):
    try:return os.path.relpath(path,base).replace(os.sep,'/')
    except ValueError:return None


def save_catalog(c,filename):
    validate(c)
    dest=Path(filename).expanduser().resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    # Preserve old catalogs before upgrading their on-disk format.
    if dest.exists():
        try:
            with dest.open('r',encoding='utf-8') as old_file:
                old_version=json.load(old_file).get('version')
            if old_version in (1, 2, 3):
                backup=dest.with_name(dest.name+f'.v{old_version}.bak')
                if not backup.exists():shutil.copy2(dest,backup)
        except (OSError,ValueError,AttributeError):
            pass  # Existing malformed files are handled by normal user backups.
    data=copy.deepcopy(c)
    for _,_,_,_,_,m in iter_media_context(data):m['relative_path']=safe_relative(m['path'],str(dest.parent))
    for key in ('video_root','audio_root'):
        if data.get(key):data[key+'_relative']=safe_relative(data[key],str(dest.parent))
    data['saved_at_utc']=datetime.now(timezone.utc).isoformat()
    temp=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=dest.parent,prefix='.sceneslate-',suffix='.tmp',delete=False) as f:
            temp=f.name;json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temp,dest)
    finally:
        if temp and os.path.exists(temp):os.unlink(temp)
    return dest


def load_catalog(filename):
    file=Path(filename).expanduser().resolve()
    with file.open('r',encoding='utf-8') as f:data=json.load(f)
    data=migrate_legacy(data)
    validate(data)
    for _,_,_,_,_,m in iter_media_context(data):
        old=m['path'];rel=m.pop('relative_path',None)
        if not os.path.isfile(old) and rel:
            candidate=canonical(file.parent/rel)
            if os.path.isfile(candidate):m['path']=candidate
    for key in ('video_root','audio_root'):
        rel=data.pop(key+'_relative',None)
        if data.get(key) and not os.path.isdir(data[key]) and rel:
            candidate=canonical(file.parent/rel)
            if os.path.isdir(candidate):data[key]=candidate
    data.pop('saved_at_utc',None)
    return data


def assigned_paths(c,kind=None):
    return {identity(m['path']) for _,_,_,k,m in iter_media(c) if kind is None or k==kind}


def empty_subshot(sub):
    return not any(t.get(kind) for t in sub['takes'] for kind in ('video','audio'))


def empty_shot(shot):
    return empty_subshot(shot) and all(empty_subshot(sub) for sub in shot.get('subshots', []))


def empty_scene(scene):
    return not any(not empty_shot(sh) for sh in scene['shots'])


def scenes_for_display(c,only_empty=False):
    for scene in c['scenes']:
        shots=[sh for sh in scene['shots'] if empty_shot(sh) or any(empty_subshot(sub) for sub in sh.get('subshots', []))] if only_empty else scene['shots']
        if not only_empty or shots or not scene['shots']:yield scene,shots


def sort_directory_entries(entries,mode='name_asc'):
    if mode not in ('name_asc','name_desc','created_asc','created_desc'):mode='name_asc'
    dirs=[e for e in entries if e[1]]; files=[e for e in entries if not e[1]]
    reverse=mode.endswith('_desc')
    key=(lambda e:(birth_timestamp(e[2])[0] if e[2] is not None else -1,e[0].name.casefold())) if mode.startswith('created') else (lambda e:e[0].name.casefold())
    return sorted(dirs,key=lambda e:e[0].name.casefold())+sorted(files,key=key,reverse=reverse)


def export_catalog_csv(c, destination):
    fields = ['Scena','Shot','Sotto-shot','Ciak','Numero manuale','Etichetta','Video','Qualità video','Percorso video',
              'Esiste video','Audio','Qualità audio','Percorso audio','Esiste audio',
              'Descrizione scena','Descrizione shot','Descrizione sotto-shot','Descrizione ciak','Annotazione ciak','Note scena (legacy)','Note shot (legacy)','Note sotto-shot (legacy)','Note ciak (legacy)']
    with open(destination, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=';');w.writeheader()
        for s, sh, sub, container in iter_containers(c):
            for t in sorted(container['takes'], key=lambda x:x['number']):
                v,a = t.get('video'),t.get('audio')
                w.writerow(dict(zip(fields,[s['number'],sh['number'],sub['name'] if sub else '',t['number'],
                    'SI' if t['manual_number'] else 'NO',label(c,s['number'],sh['number'],sub['name'] if sub else None),
                    Path(v['path']).name if v else '',v['quality'] if v else '',v['path'] if v else '',
                    'SI' if v and Path(v['path']).is_file() else ('NO' if v else ''),
                    Path(a['path']).name if a else '',a['quality'] if a else '',a['path'] if a else '',
                    'SI' if a and Path(a['path']).is_file() else ('NO' if a else ''),
                    s.get('description',''),sh.get('description',''),sub.get('description','') if sub else '',
                    t.get('description',''),t.get('annotation',''),s.get('notes',''),sh.get('notes',''),
                    sub.get('notes','') if sub else '',t.get('notes','')])))


def export_shots_csv(c, destination):
    fields=['Scena','Shot','Sotto-shot','Etichetta','Ciak (video[B/R/S] + audio[B/R/S])','Ciak incompleti','Descrizione scena','Descrizione shot','Descrizione sotto-shot']
    with open(destination,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter=';');w.writerow(fields)
        for s,sh,sub,container in iter_containers(c):
            desc=' | '.join(f"{t['number']}: "+' + '.join(
                f"{k.upper()} {Path(t[k]['path']).name} [{t[k]['quality']}]" for k in ('video','audio') if t.get(k))
                for t in sorted(container['takes'], key=lambda x:x['number']))
            incomplete=sum(bool(t.get('video'))!=bool(t.get('audio')) for t in container['takes'])
            w.writerow([s['number'],sh['number'],sub['name'] if sub else '',
                label(c,s['number'],sh['number'],sub['name'] if sub else None),desc,incomplete,
                s.get('description',''),sh.get('description',''),sub.get('description','') if sub else ''])


def resolve_rows(c):
    """Resolve fields are per-media, not per-usage; skip contradictory shared media."""
    grouped=defaultdict(list)
    for s,sh,sub,t,kind,m in iter_media_context(c):
        grouped[identity(m['path'])].append((s,sh,sub,t,kind,m))
    rows=[];warnings=[]
    for _,entries in sorted(grouped.items()):
        unique={(s['number'],sh['number'],sub['id'] if sub else None,t['number'],k,m['quality'])
                for s,sh,sub,t,k,m in entries}
        file=entries[0][5]['path']
        if len(unique)>1:
            warnings.append(f"ESCLUSO {Path(file).name}: usato in {len(unique)} punti diversi del catalogo; Resolve non può associare più valori Scene/Shot/Take allo stesso file. Il CSV completo conserva tutti gli usi.")
            continue
        s,sh,sub,t,kind,med=entries[0];q=med['quality']
        if not Path(file).is_file():warnings.append(f'ATTENZIONE {Path(file).name}: file non disponibile.')
        other=t.get('audio' if kind=='video' else 'video')
        details=f"Valutazione {kind}: {QUALITIES[q]} ({q})."
        if sub:details+=f" Inquadratura: {sub['name']}."
        if other:details+=f" Abbinato a: {Path(other['path']).name}."
        notes=' '.join(x.strip() for x in (s.get('description',''),sh.get('description',''),
            sub.get('description','') if sub else '',t.get('description',''),
            t.get('annotation',''),med.get('notes','')) if x.strip())
        if notes:details+=' Note: '+notes.replace('\n',' / ')
        sub_keyword=(f", INQUADRATURA_{sub['name'].replace(',', '_')}" if sub else '')
        rows.append({'File Name':Path(file).name,'Clip Directory':str(Path(file).parent),
             'Scene':str(s['number']),'Shot':str(sh['number']),'Take':str(t['number']),
             'Keywords':f"SCENA_{s['number']}, SHOT_{sh['number']}{sub_keyword}, CIAK_{t['number']}, QUALITA_{q}, {kind.upper()}",
             'Comments':details})
    by_name=defaultdict(set)
    for row in rows:by_name[row['File Name'].casefold()].add(row['Clip Directory'])
    for name,folders in by_name.items():
        if len(folders)>1:warnings.append(f'ATTENZIONE {name}: nome ripetuto in cartelle differenti; in Resolve verifica il matching sul percorso.')
    return rows,warnings


def export_resolve_csv(c,destination):
    rows,warnings=resolve_rows(c)
    with open(destination,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['File Name','Clip Directory','Scene','Shot','Take','Keywords','Comments'],lineterminator='\r\n');w.writeheader();w.writerows(rows)
    return len(rows),warnings


def export_all(c,directory):
    dest=Path(directory);dest.mkdir(parents=True,exist_ok=True)
    export_catalog_csv(c,dest/'catalogo_completo.csv')
    export_shots_csv(c,dest/'riepilogo_shot.csv')
    count,warnings=export_resolve_csv(c,dest/'resolve_metadata.csv')
    with (dest/'report_esportazione.txt').open('w',encoding='utf-8') as f:
        f.write(f'SceneSlate 3.1 - report di esportazione\nRighe Resolve: {count}\n\n')
        f.write('\n'.join(warnings) if warnings else 'Nessuna ambiguità rilevata.\n')
        f.write('\n\nATTENZIONE: accoppiamento catalografico, NON sincronizzazione timecode/audio.\n')
    return count,warnings
