"""Non-destructive Final Cut Pro 7 XML (xmeml v5) timeline interchange.

Generated XML references original media via file:// URI. Import via Resolve's
File > Import > Timeline. These are timelines, not native synced Media Pool clips.
"""
from __future__ import annotations
from pathlib import Path
import math
import re
from xml.etree import ElementTree as ET

import scene_sync


def safe_name(value):
    return re.sub(r'[^a-zA-Z0-9_-]+','_',str(value)).strip('_')[:75] or 'unnamed'


def fps_parameters(fps):
    fps=float(fps)
    for target,tb,ntsc in ((23.976,24,'TRUE'),(24,24,'FALSE'),(25,25,'FALSE'),
                           (29.97,30,'TRUE'),(30,30,'FALSE'),(50,50,'FALSE'),
                           (59.94,60,'TRUE'),(60,60,'FALSE')):
        if abs(fps-target)<0.01:return tb,ntsc
    raise ValueError('Timeline FPS must be 23.976, 24, 25, 29.97, 30, 50, 59.94 or 60')


def node(parent,name,value=None,**attributes):
    e=ET.SubElement(parent,name,attributes)
    if value is not None:e.text=str(value)
    return e


def rate(parent,fps):
    tb,ntsc=fps_parameters(fps)
    r=node(parent,'rate');node(r,'timebase',tb);node(r,'ntsc',ntsc)


def file_element(parent,path,info,fps,file_id):
    f=node(parent,'file',id=file_id)
    node(f,'name',Path(path).name)
    node(f,'pathurl',Path(path).resolve().as_uri())
    node(f,'duration',max(1,round(info['duration']*fps)))
    rate(f,fps)
    media=node(f,'media')
    if info['video']:
        video=node(media,'video');sample=node(video,'samplecharacteristics')
        rate(sample,fps)
        node(sample,'width',info['width'] or 1920)
        node(sample,'height',info['height'] or 1080)
        node(sample,'anamorphic','FALSE')
        node(sample,'pixelaspectratio','square')
        node(sample,'fielddominance','none')
    if info['audio']:
        aud=node(media,'audio');sample=node(aud,'samplecharacteristics')
        node(sample,'depth',16)
        node(sample,'samplerate',info['sample_rate'] or 48000)
        node(aud,'channelcount',info['channels'] or 1)
    return f


def clip_element(track,clip_id,path,info,kind,fps,timeline_start,source_in,frames,links=(),audio_track_index=1):
    c=node(track,'clipitem',id=clip_id)
    node(c,'name',Path(path).name)
    node(c,'enabled','TRUE')
    node(c,'duration',max(1,round(info['duration']*fps)))
    rate(c,fps)
    node(c,'start',timeline_start)
    node(c,'end',timeline_start+frames)
    src=max(0,round(source_in*fps))
    node(c,'in',src)
    node(c,'out',src+frames)
    file_element(c,path,info,fps,'file-'+safe_name(clip_id))
    if kind=='audio':
        s=node(c,'sourcetrack');node(s,'mediatype','audio');node(s,'trackindex',audio_track_index)
    for link_id,link_kind,track_index in links:
        link=node(c,'link');node(link,'linkclipref',link_id)
        node(link,'mediatype',link_kind)
        node(link,'trackindex',track_index)
    return c


def planned_segment(take,fps,warnings,reference):
    video=take.get('video');audio=take.get('audio')
    if not video and not audio:return None
    vinfo=ainfo=None
    try:
        if video:vinfo=scene_sync.media_probe(video['path'])
        if audio:ainfo=scene_sync.media_probe(audio['path'])
    except (OSError,RuntimeError,ValueError) as exc:
        warnings.append(f'SKIP {reference}: cannot inspect media: {exc}')
        return None
    video_in=audio_in=0.
    use_audio=bool(audio)
    if video and audio:
        sync_status=scene_sync.effective_status(take)
        if sync_status!='OK':
            warnings.append(f'{reference}: sync {sync_status}; exporting video alone (external audio omitted to avoid false alignment)')
            use_audio=False
        else:
            lag=float(take['sync']['offset_seconds'])
            video_in=max(0.,-lag)
            audio_in=max(0.,lag)
            # FCP7 XML stores source in/out points as *integer timeline
            # frames*. Even a sub-millisecond sync estimate is rounded on
            # export. Do not claim the XML remains sample-accurate.
            frame_error = ((round(audio_in*fps)/fps-audio_in) -
                           (round(video_in*fps)/fps-video_in))*1000
            if abs(frame_error) > 5.0:
                warning = (f'{reference}: FCP7 XML frame quantization ' 
                           f'{frame_error:+.1f} ms at {fps:g} fps; '
                           'fine-adjust audio in Resolve if precision matters')
                if warning not in warnings:
                    warnings.append(warning)
    if video and not vinfo['video']:
        warnings.append(f'SKIP {reference}: no video stream')
        return None
    if use_audio and not ainfo['audio']:
        warnings.append(f'SKIP {reference}: no audio stream')
        return None
    duration=min([vinfo['duration']-video_in] if video else [ainfo['duration']-audio_in])
    if video and use_audio:duration=min(duration,ainfo['duration']-audio_in)
    frames=int(math.floor(duration*fps+1e-8))
    if frames<1:
        warnings.append(f'SKIP {reference}: no shared playback time')
        return None
    return {'video':video,'audio':audio if use_audio else None,'vinfo':vinfo,'ainfo':ainfo,
            'video_in':video_in,'audio_in':audio_in,'frames':frames, 'reference':reference}


def write_timeline(filepath,name,takes,fps=25.,warnings=None):
    """Write a single timeline of (display_label,take) pairs; return clip count."""
    warnings=warnings if warnings is not None else []
    segments=[]
    for label,take in takes:
        item=planned_segment(take,fps,warnings,label)
        if item:segments.append(item)
    if not segments:return 0
    root=ET.Element('xmeml',version='5')
    sequence=node(root,'sequence',id='sequence-'+safe_name(name))
    node(sequence,'name',name)
    total=sum(s['frames'] for s in segments)
    node(sequence,'duration',total)
    rate(sequence,fps)
    node(sequence,'in',0);node(sequence,'out',total)
    media=node(sequence,'media')
    v=node(media,'video');fmt=node(v,'format');sample=node(fmt,'samplecharacteristics')
    rate(sample,fps)
    # Source dimensions may differ. Resolve's timeline settings can be adjusted on import.
    dimensions=next((s['vinfo'] for s in segments if s['video']),{})
    node(sample,'width',dimensions.get('width') or 1920)
    node(sample,'height',dimensions.get('height') or 1080)
    node(sample,'anamorphic','FALSE');node(sample,'pixelaspectratio','square');node(sample,'fielddominance','none')
    video_track=node(v,'track');node(video_track,'enabled','TRUE');node(video_track,'locked','FALSE')
    a=node(media,'audio')
    max_channels=max((min(16,s['ainfo']['channels'] or 1) for s in segments if s['audio']),default=1)
    node(a,'numOutputChannels',max(2,max_channels))
    audio_tracks=[]
    for _ in range(max_channels):
        audio_track=node(a,'track');node(audio_track,'enabled','TRUE');node(audio_track,'locked','FALSE')
        audio_tracks.append(audio_track)
    pos=0
    for index,segment in enumerate(segments,1):
        vclip=f'video-{index}' if segment['video'] else None
        channels=min(16,segment['ainfo']['channels'] or 1) if segment['audio'] else 0
        audio_ids=[f'audio-{index}-ch-{ch}' for ch in range(1,channels+1)]
        links=([(vclip,'video',1)] if vclip else [])+[(acid,'audio',ch) for ch,acid in enumerate(audio_ids,1)]
        if segment['video']:
            clip_element(video_track,vclip,segment['video']['path'],segment['vinfo'],'video',fps,
                         pos,segment['video_in'],segment['frames'],links)
        for ch,audio_id in enumerate(audio_ids,1):
            clip_element(audio_tracks[ch-1],audio_id,segment['audio']['path'],segment['ainfo'],'audio',fps,
                         pos,segment['audio_in'],segment['frames'],links,audio_track_index=ch)
        pos+=segment['frames']
    filepath=Path(filepath);filepath.parent.mkdir(parents=True,exist_ok=True)
    ET.indent(root,space='  ')
    ET.ElementTree(root).write(filepath,encoding='utf-8',xml_declaration=True,short_empty_elements=True)
    return len(segments)


def export_timelines(c,directory,modes=('take','shot','scene'),fps=25.):
    """Export take, shot and scene review timelines as independent XML files."""
    from scene_core import iter_containers
    base=Path(directory)
    warnings=[];counts={'take':0,'shot':0,'scene':0}
    for scene in sorted(c['scenes'],key=lambda s:s['number']):
        all_scene=[]
        for shot in sorted(scene['shots'],key=lambda s:s['number']):
            shot_takes=[]
            for ss in [None]+list(shot.get('subshots',[])):
                container=ss if ss is not None else shot
                parts=[f'S{scene["number"]:03d}',f'SH{shot["number"]:03d}']
                if ss is not None:parts.append(ss['name'])
                prefix='_'.join(parts)
                for take in sorted(container['takes'],key=lambda t:t['number']):
                    label=prefix+f'_T{take["number"]:03d}'
                    shot_takes.append((label,take));all_scene.append((label,take))
                    if 'take' in modes:
                        file=base/'xml_takes'/f'{safe_name(label)}.xml'
                        if write_timeline(file,label,[(label,take)],fps,warnings):counts['take']+=1
            if 'shot' in modes and shot_takes:
                name=f'S{scene["number"]:03d}_SH{shot["number"]:03d}'
                if write_timeline(base/'xml_shots'/f'{name}.xml',name,shot_takes,fps,warnings):counts['shot']+=1
        if 'scene' in modes and all_scene:
            name=f'Scene_{scene["number"]:03d}'
            if write_timeline(base/'xml_scenes'/f'{name}.xml',name,all_scene,fps,warnings):counts['scene']+=1
    return counts,warnings
