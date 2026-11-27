"""SceneSlate 3.12.0-experimental.1 catalog engine: scene/shot/subshot/take with video/audio pairs.

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

import scene_sync

VERSION = 6
QUALITIES = {'B': 'Buona', 'R': 'Riserva', 'S': 'Scarto'}
VIDEO_EXT = {'.mov','.mp4','.mxf','.avi','.mkv','.mts','.m2ts','.mpg','.mpeg','.wmv','.webm','.r3d','.braw','.mp4v','.m4v'}
AUDIO_EXT = {'.wav','.bwf','.mp3','.flac','.aif','.aiff','.m4a','.ogg','.wma','.caf'}

class CatalogError(ValueError):
    pass


def new_catalog():
    return {'version': VERSION, 'name': 'New catalog',
            'settings': {'scene_label': 'Scene', 'shot_label': 'Shot', 'separator': ' / ', 'padding': 0, 'timeline_fps':25.0},
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
    c['scenes'].append({'number': number, 'description': '', 'notes': '', 'shots': [], 'link_group': None})
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
    scene['shots'].append({'number':number,'description':'','notes':'','takes':[],'subshots':[],'link_group': None})
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
    item = {'id': uuid4().hex, 'name': name, 'description': '', 'notes': '', 'takes': [], 'link_group': None}
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
    # Resolve symlinks/junctions and Windows 8.3 aliases consistently.
    # This also makes relative media paths portable when the original path
    # uses RUNNER~1 while the saved catalog path uses its long spelling.
    return os.path.realpath(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


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


def ensure_media_target(c, scene_number, shot_number, subshot_id=None):
    """Once angles exist, only sub-shots may receive new media or take rows.

    Legacy direct-shot takes are left untouched, so old catalogs remain readable.
    """
    shot = shot_for(c, scene_number, shot_number)
    if shot is not None and subshot_id is None and shot.get('subshots'):
        raise CatalogError('This shot has sub-shots. Select a sub-shot to attach media or add takes.')


def add_take(c, scene_number, shot_number, number=None, subshot_id=None):
    container = container_for(c, scene_number, shot_number, subshot_id)
    if container is None:
        raise CatalogError('Seleziona uno shot o sotto-shot.')
    ensure_media_target(c, scene_number, shot_number, subshot_id)
    used = {t['number'] for t in container['takes']}
    next_auto = max(used, default=0) + 1
    number = next_auto if number is None else positive_number(number)
    if number in used:
        raise CatalogError(f'Ciak {number} già presente.')
    order = max((t.get('order', 0) for t in container['takes']), default=0) + 1
    take = {'number': number, 'manual_number': number != next_auto,
            'order': order, 'video': None, 'audio': None,
            'description': '', 'annotation': '', 'notes': '', 'sync': None}
    container['takes'].append(take)
    container['takes'].sort(key=lambda t: t['number'])
    return take


def set_take_number(c,scene_number,shot_number,old,new,subshot_id=None):
    container=container_for(c,scene_number,shot_number,subshot_id)
    take=take_for(c,scene_number,shot_number,old,subshot_id)
    if take is None:raise CatalogError('Ciak non trovato.')
    new=positive_number(new)
    if new == old:
        take['manual_number']=True
        return take['number']
    others=sorted([t for t in container['takes'] if t is not take], key=lambda t:(t['number'], t.get('order',0)))
    occupied={t['number'] for t in others}
    shifts=[]
    cursor=new
    while cursor in occupied:
        victim=next(t for t in others if t['number']==cursor)
        shifts.append(victim)
        cursor += 1
    for victim in reversed(shifts):
        victim['number'] += 1
    take['number']=new
    take['manual_number']=True
    container['takes'].sort(key=lambda t:(t['number'], t.get('order',0)))
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
    ensure_media_target(c, scene_number, shot_number, subshot_id)
    info=media_info(path,quality)
    if any(t[kind] and identity(t[kind]['path'])==identity(info['path']) for t in sh['takes']):
        return (None,False)
    target=take_for(c,scene_number,shot_number,take_number,subshot_id) if take_number is not None else None
    if take_number is not None and target is None:raise CatalogError('Ciak di destinazione non trovato.')
    if target is not None and target[kind] is not None:
        raise CatalogError(f'Ciak {target["number"]}: lato {kind} già occupato. Usa un nuovo ciak oppure rimuovi il lato.')
    if target is None:target=add_take(c,scene_number,shot_number,subshot_id=subshot_id)
    target[kind]=info
    target['sync']=None  # Pair changed: a prior alignment is no longer trustworthy.
    return (target,True)


def remove_media(c,scene_number,shot_number,take_number,kind,subshot_id=None):
    take=take_for(c,scene_number,shot_number,take_number,subshot_id)
    if take is None:raise CatalogError('Ciak non trovato.')
    if kind not in ('video','audio'):raise CatalogError('Lato non valido.')
    take[kind]=None
    take['sync']=None
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
            sync=take.get('sync')
            if sync is not None and (not isinstance(sync,dict) or sync.get('status') not in scene_sync.SYNC_STATUSES):
                raise CatalogError(f'Invalid sync record in {prefix}/{tn}')
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
        if scene.get('link_group') is not None and not isinstance(scene.get('link_group'), str):
            raise CatalogError('Collegamento scena non valido.')
        if n in scene_nums:raise CatalogError(f'Scena duplicata: {n}')
        scene_nums.add(n)
        shot_nums = set()
        for shot in scene['shots']:
            sn = positive_number(shot['number'])
            if not isinstance(shot.get('description'),str):raise CatalogError('Descrizione shot non valida.')
            if shot.get('link_group') is not None and not isinstance(shot.get('link_group'), str):
                raise CatalogError('Collegamento shot non valido.')
            if sn in shot_nums:raise CatalogError(f'Shot duplicato: {n}/{sn}')
            shot_nums.add(sn)
            validate_takes(shot, f'{n}/{sn}')
            if not isinstance(shot.get('subshots'), list):
                raise CatalogError(f'Sotto-shot non validi in {n}/{sn}')
            names, ids = set(), set()
            for sub in shot['subshots']:
                name = clean_subshot_name(sub.get('name'))
                if not isinstance(sub.get('description'),str):raise CatalogError('Descrizione sotto-shot non valida.')
                if sub.get('link_group') is not None and not isinstance(sub.get('link_group'), str):
                    raise CatalogError('Collegamento sotto-shot non valido.')
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
    if float(st.get('timeline_fps',25)) not in (23.976,24,25,29.97,30,50,59.94,60):
        raise CatalogError('Unsupported XML timeline frame rate')
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
        data['version'] = 4
    if data.get('version') == 4:
        data = copy.deepcopy(data)
        for scene in data.get('scenes', []):
            for shot in scene.get('shots', []):
                for container in [shot] + shot.get('subshots', []):
                    for take in container.get('takes', []):
                        take.setdefault('sync', None)
        data.setdefault('settings', {}).setdefault('timeline_fps', 25.0)
        data['version'] = 5
    if data.get('version') == 5:
        data = copy.deepcopy(data)
        for scene in data.get('scenes', []):
            scene.setdefault('link_group', None)
            for shot in scene.get('shots', []):
                shot.setdefault('link_group', None)
                for sub in shot.get('subshots', []):
                    sub.setdefault('link_group', None)
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
    sub['link_group'] = None
    sub['name'] = unique_subshot_name(shot, clean_subshot_name(name if name is not None else sub['name']))
    shot.setdefault('subshots', []).append(sub)
    return sub


def _append_shot(scene, item):
    sh = copy.deepcopy(item)
    sh['link_group'] = None
    existing = {x['number'] for x in scene['shots']}
    if sh['number'] in existing:
        sh['number'] = max(existing, default=0)+1
    for sub in sh.get('subshots', []):
        sub['id'] = uuid4().hex
        sub['link_group'] = None
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
            if data['takes'] and (dst.get('subshots') or data.get('subshots')):
                raise CatalogError('This shot has sub-shots. Paste takes into a sub-shot instead.')
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



def _kind_and_node(c, scene_number, shot_number=None, subshot_id=None):
    if subshot_id is not None:
        node = subshot_for(c, scene_number, shot_number, subshot_id)
        kind = 'subshot'
    elif shot_number is not None:
        node = shot_for(c, scene_number, shot_number)
        kind = 'shot'
    else:
        node = scene_for(c, scene_number)
        kind = 'scene'
    return kind, node


def node_ref(scene_number, shot_number=None, subshot_id=None):
    if subshot_id is not None:
        return f'subshot:{scene_number}:{shot_number}:{subshot_id}'
    if shot_number is not None:
        return f'shot:{scene_number}:{shot_number}'
    return f'scene:{scene_number}'


def iter_nodes(c, kind=None):
    for scene in sorted(c['scenes'], key=lambda s: s['number']):
        if kind in (None, 'scene'):
            yield node_ref(scene['number']), 'scene', scene
        for shot in sorted(scene['shots'], key=lambda sh: sh['number']):
            if kind in (None, 'shot'):
                yield node_ref(scene['number'], shot['number']), 'shot', shot
            for sub in shot.get('subshots', []):
                if kind in (None, 'subshot'):
                    yield node_ref(scene['number'], shot['number'], sub['id']), 'subshot', sub


def linked_refs(c, scene_number, shot_number=None, subshot_id=None):
    kind, node = _kind_and_node(c, scene_number, shot_number, subshot_id)
    if node is None:
        raise CatalogError('Elemento collegabile non trovato.')
    gid = node.get('link_group')
    if not gid:
        return [node_ref(scene_number, shot_number, subshot_id)]
    return [ref for ref, node_kind, other in iter_nodes(c, kind) if other.get('link_group') == gid]


def _strip_links(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key == 'link_group':
                out[key] = None
            else:
                out[key] = _strip_links(value)
        return out
    if isinstance(obj, list):
        return [_strip_links(x) for x in obj]
    return copy.deepcopy(obj)


def linked_take_targets(c, scene_number, shot_number, subshot_id=None):
    """Explicit sub-shot links only; direct shots also inherit matching scene links.

    No relationship here ever creates, removes or renames a structural node.
    Resolve transitively so overlapping scene and shot groups stay consistent.
    """
    nodes={}
    memberships=defaultdict(list)
    for scene,shot,sub,node in iter_containers(c):
        n,h=scene['number'],shot['number']
        key=(n,h,sub['id'] if sub else None)
        groups=[]
        if sub:
            if sub.get('link_group'):groups.append(('subshot',sub['link_group']))
        else:
            if scene.get('link_group'):groups.append(('scene-shot',scene['link_group'],h))
            if shot.get('link_group'):groups.append(('shot',shot['link_group']))
        nodes[key]=(node,groups)
        for group in groups:memberships[group].append(key)
    queue=[(scene_number,shot_number,subshot_id)]
    seen=set()
    result=[]
    while queue:
        key=queue.pop()
        if key in seen or key not in nodes:continue
        seen.add(key)
        node,groups=nodes[key]
        result.append((key,node))
        for group in groups:queue.extend(memberships[group])
    return result


def propagate_links(c, scene_number, shot_number=None, subshot_id=None, *, metadata_only=False):
    """Mirror content without replacing any scene/shot/sub-shot structure."""
    kind,source=_kind_and_node(c,scene_number,shot_number,subshot_id)
    if source is None:raise CatalogError('Elemento collegabile non trovato.')
    changed=0
    if kind=='scene':
        gid=source.get('link_group')
        if not gid:return 0
        for other in c['scenes']:
            if other is source or other.get('link_group')!=gid:continue
            for key in ('description','notes'):other[key]=copy.deepcopy(source.get(key,''))
            changed+=1
        if not metadata_only:
            for sh in source['shots']:
                changed+=propagate_links(c,scene_number,sh['number'])
        return changed
    for _,other in linked_take_targets(c,scene_number,shot_number,subshot_id):
        if other is source:continue
        for key in ('description','notes'):
            other[key]=copy.deepcopy(source.get(key,''))
        if not metadata_only:other['takes']=copy.deepcopy(source['takes'])
        changed+=1
    return changed


def configure_links(c, scene_number, shot_number=None, subshot_id=None, member_refs=None):
    kind, source = _kind_and_node(c, scene_number, shot_number, subshot_id)
    if source is None:
        raise CatalogError('Elemento collegabile non trovato.')
    source_ref = node_ref(scene_number, shot_number, subshot_id)
    selected = {source_ref}
    if member_refs:
        for ref in member_refs:
            selected.add(ref)
    valid_refs = {}
    for ref, node_kind, node in iter_nodes(c, kind):
        valid_refs[ref] = node
    for ref in tuple(selected):
        if ref not in valid_refs:
            raise CatalogError('Selezione collegamenti non valida.')
    if len(selected) <= 1:
        source['link_group'] = None
        return None
    gid = source.get('link_group') or next((valid_refs[ref].get('link_group') for ref in selected if valid_refs[ref].get('link_group')), None) or uuid4().hex
    for ref, node_kind, node in iter_nodes(c, kind):
        if node.get('link_group') == gid and ref not in selected:
            node['link_group'] = None
    for ref in selected:
        valid_refs[ref]['link_group'] = gid
    propagate_links(c, scene_number, shot_number, subshot_id)
    return gid


def clear_take_targets(c, scene_number, shot_number=None, subshot_id=None):
    """Clear the selected local subtree plus actual linked take containers.

    A linked parent never implicitly owns another parent's sub-shots.
    """
    kind,source=_kind_and_node(c,scene_number,shot_number,subshot_id)
    if source is None:raise CatalogError('Elemento collegabile non trovato.')
    result={}
    for scene,shot,sub,node in iter_containers(c):
        n,h=scene['number'],shot['number']
        u=sub['id'] if sub else None
        if n!=scene_number or (shot_number is not None and h!=shot_number):continue
        if subshot_id is not None and u!=subshot_id:continue
        for key,other in linked_take_targets(c,n,h,u):result[key]=other
    return list(result.values())


def clear_take_content(c, scene_number, shot_number=None, subshot_id=None):
    targets=clear_take_targets(c,scene_number,shot_number,subshot_id)
    count=sum(len(node['takes']) for node in targets)
    for node in targets:
        node['takes'].clear()
    return count


def file_time_from_path(path):
    try:return birth_timestamp(Path(path).stat())[0]
    except (OSError,ValueError):return float('inf')


def safe_relative(path,base):
    try:return os.path.relpath(canonical(path),canonical(base)).replace(os.sep,'/')
    except ValueError:return None


def save_catalog(c,filename):
    validate(c)
    dest=Path(filename).expanduser().resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    # Preserve old catalogs before upgrading their on-disk format.
    if dest.exists():
        try:
            with dest.open('r',encoding='utf-8') as old_file:
                old_version=json.load(old_file).get('version')
            if old_version in (1, 2, 3, 4, 5):
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
    fields = ['Scene','Shot','Sub-shot','Take','Manual number','Label','Video','Video quality','Video path',
              'Video exists','Audio','Audio quality','Audio path','Audio exists',
              'Scene description','Shot description','Sub-shot description','Take description','Take annotation','Sync status','Sync offset (s)','Sync score','Sync method','Sync error','Scene notes (legacy)','Shot notes (legacy)','Sub-shot notes (legacy)','Take notes (legacy)']
    with open(destination, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=';');w.writeheader()
        for s, sh, sub, container in iter_containers(c):
            for t in sorted(container['takes'], key=lambda x:x['number']):
                v,a = t.get('video'),t.get('audio')
                w.writerow(dict(zip(fields,[s['number'],sh['number'],sub['name'] if sub else '',t['number'],
                    'YES' if t['manual_number'] else 'NO',label(c,s['number'],sh['number'],sub['name'] if sub else None),
                    Path(v['path']).name if v else '',v['quality'] if v else '',v['path'] if v else '',
                    'YES' if v and Path(v['path']).is_file() else ('NO' if v else ''),
                    Path(a['path']).name if a else '',a['quality'] if a else '',a['path'] if a else '',
                    'YES' if a and Path(a['path']).is_file() else ('NO' if a else ''),
                    s.get('description',''),sh.get('description',''),sub.get('description','') if sub else '',
                    t.get('description',''),t.get('annotation',''),scene_sync.effective_status(t),
                    (t.get('sync') or {}).get('offset_seconds',''),(t.get('sync') or {}).get('score',''),
                    (t.get('sync') or {}).get('method',''),(t.get('sync') or {}).get('error',''),
                    s.get('notes',''),sh.get('notes',''),
                    sub.get('notes','') if sub else '',t.get('notes','')])))


def export_shots_csv(c, destination):
    fields=['Scene','Shot','Sub-shot','Label','Takes (video[B/R/S] + audio[B/R/S])','Incomplete takes','Sync status','Scene description','Shot description','Sub-shot description']
    with open(destination,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f,delimiter=';');w.writerow(fields)
        for s,sh,sub,container in iter_containers(c):
            desc=' | '.join(f"{t['number']}: "+' + '.join(
                f"{k.upper()} {Path(t[k]['path']).name} [{t[k]['quality']}]" for k in ('video','audio') if t.get(k))
                for t in sorted(container['takes'], key=lambda x:x['number']))
            incomplete=sum(bool(t.get('video'))!=bool(t.get('audio')) for t in container['takes'])
            w.writerow([s['number'],sh['number'],sub['name'] if sub else '',
                label(c,s['number'],sh['number'],sub['name'] if sub else None),desc,incomplete,
                scene_sync.node_status(container['takes']),s.get('description',''),sh.get('description',''),sub.get('description','') if sub else ''])


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
            warnings.append(f"SKIPPED {Path(file).name}: used at {len(unique)} catalog locations. Resolve cannot assign multiple Scene/Shot/Take values to one file. The full catalog CSV preserves all uses.")
            continue
        s,sh,sub,t,kind,med=entries[0];q=med['quality']
        if not Path(file).is_file():warnings.append(f'WARNING {Path(file).name}: file not found.')
        other=t.get('audio' if kind=='video' else 'video')
        details=f"{kind.capitalize()} rating: {dict(B='Good', R='Reserve', S='Reject')[q]} ({q})."
        if sub:details+=f" Sub-shot: {sub['name']}."
        if other:details+=f" Paired with: {Path(other['path']).name}."
        notes=' '.join(x.strip() for x in (s.get('description',''),sh.get('description',''),
            sub.get('description','') if sub else '',t.get('description',''),
            t.get('annotation',''),med.get('notes','')) if x.strip())
        if notes:details+=' Notes: '+notes.replace('\n',' / ')
        sub_keyword=(f", SUBSHOT_{sub['name'].replace(',', '_')}" if sub else '')
        rows.append({'File Name':Path(file).name,'Clip Directory':str(Path(file).parent),
             'Scene':str(s['number']),'Shot':str(sh['number']),'Take':str(t['number']),
             'Keywords':f"SCENE_{s['number']}, SHOT_{sh['number']}{sub_keyword}, TAKE_{t['number']}, QUALITY_{q}, {kind.upper()}",
             'Comments':details})
    by_name=defaultdict(set)
    for row in rows:by_name[row['File Name'].casefold()].add(row['Clip Directory'])
    for name,folders in by_name.items():
        if len(folders)>1:warnings.append(f'WARNING {name}: filename exists in multiple directories; verify path matching in Resolve.')
    return rows,warnings


def export_resolve_csv(c,destination):
    rows,warnings=resolve_rows(c)
    with open(destination,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['File Name','Clip Directory','Scene','Shot','Take','Keywords','Comments'],lineterminator='\r\n');w.writeheader();w.writerows(rows)
    return len(rows),warnings


def export_all(c,directory,modes=('csv',),fps=None):
    """Export CSV plus optional XMEML sequences. Return old (rows, warnings) API."""
    modes=set(modes)
    valid={'csv','take','shot','scene'}
    if not modes.issubset(valid):raise CatalogError('Unsupported export mode: '+str(modes-valid))
    dest=Path(directory);dest.mkdir(parents=True,exist_ok=True)
    count=0;warnings=[]
    if 'csv' in modes:
        export_catalog_csv(c,dest/'full_catalog.csv')
        export_shots_csv(c,dest/'shot_summary.csv')
        count,warnings=export_resolve_csv(c,dest/'resolve_metadata.csv')
    xml_modes=modes & {'take','shot','scene'}
    counts={}
    if xml_modes:
        import scene_xml
        counts,xml_warnings=scene_xml.export_timelines(c,dest,modes=xml_modes,
            fps=fps if fps is not None else c.get('settings',{}).get('timeline_fps',25))
        warnings.extend(xml_warnings)
    with (dest/'export_report.txt').open('w',encoding='utf-8') as f:
        f.write(f'SceneSlate 3.12.0-experimental.1 - export report\nResolve metadata rows: {count}\n')
        f.write(f'Export modes: {", ".join(sorted(modes))}\n')
        for mode,n in counts.items():f.write(f'XML {mode} timelines: {n}\n')
        f.write('\n')
        errors=[w for w in warnings if w.startswith('SKIP ') and not w.startswith('SKIPPED ')]
        omissions=[w for w in warnings if w.startswith('SKIPPED ') or 'external audio omitted' in w]
        diagnostics=[w for w in warnings if w not in errors and w not in omissions]
        f.write('Export errors (skipped timeline segments):\n'+'\n'.join(errors)+'\n')
        f.write('Deliberate metadata/audio omissions:\n'+'\n'.join(omissions)+'\n')
        f.write('Other diagnostics:\n'+'\n'.join(diagnostics)+'\n')
        f.write('\n\nNOTE: only OK waveform matches export paired external audio. '
                'Unverified audio is omitted from the XML, not silently aligned. '
                'XML is an editable timeline, not a native Media Pool sync clip. '
                'Original media remains unmodified.\n')
    return count,warnings


def media_assignments(c, path, kind):
    """Occurrences of one exact source, grouped by effective link membership."""
    groups=[]
    for scene,shot,sub,take,side,media in iter_media_context(c):
        if side!=kind or identity(media['path'])!=identity(path):
            continue
        n,h=scene['number'],shot['number']
        u=sub['id'] if sub else None
        name=sub['name'].casefold() if sub else None
        num=take['number']
        keys=set()
        if not sub and scene.get('link_group'):
            keys.add(('scene',scene['link_group'],h,num))
        if not sub and shot.get('link_group'):
            keys.add(('shot',shot['link_group'],num))
        if sub and sub.get('link_group'):
            keys.add(('subshot',sub['link_group'],num))
        items=[{'target':(n,h,u,num),'label':label(c,n,h,sub['name'] if sub else None)}]
        remaining=[]
        for group in groups:
            if keys & group['keys']:
                keys.update(group['keys']);items.extend(group['items'])
            else:
                remaining.append(group)
        remaining.append({'keys':keys,'items':items})
        groups=remaining
    for group in groups:
        group['items'].sort(key=lambda item:(item['target'][0],item['target'][1],item['label'],item['target'][3]))
    return sorted(groups,key=lambda g:g['items'][0]['target'][:2])
