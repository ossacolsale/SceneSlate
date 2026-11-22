"""Background-safe, non-destructive waveform matching for paired camera/external audio.

An offset in seconds is the external audio *source* position corresponding to
video time zero. Positive values mean the recorder started earlier; negative
values mean the recorder started later. No source media is modified.
"""
from __future__ import annotations
import array
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timezone

SAMPLE_RATE = 800
MAX_SECONDS = 90
MAX_OFFSET_SECONDS = 60
MIN_OVERLAP_SECONDS = 8
SYNC_STATUSES = {'OK','REVIEW','KO','PENDING'}


def executables():
    ffmpeg = os.environ.get('SCENESLATE_FFMPEG') or shutil.which('ffmpeg')
    ffprobe = os.environ.get('SCENESLATE_FFPROBE') or shutil.which('ffprobe')
    if ffmpeg and not ffprobe:
        sibling=Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        if sibling.is_file(): ffprobe=str(sibling)
    return ffmpeg, ffprobe


def fingerprint(video, audio):
    values=[]
    for path in (video,audio):
        p=Path(path)
        try:
            s=p.stat()
            values.append([str(p.resolve()),s.st_size,s.st_mtime_ns])
        except OSError:
            values.append([str(p),None,None])
    return values


def sync_record(status='PENDING', *, offset_seconds=None, score=None, error='', method='waveform', signature=None):
    return {'status':status,'offset_seconds':offset_seconds, 'score':score,
            'method':method,'error':str(error)[:350], 'signature':signature,
            'checked_at':datetime.now(timezone.utc).isoformat()}


def effective_status(take):
    if not take.get('video') or not take.get('audio'):return 'SINGLE'
    sync=take.get('sync') or {}
    if sync.get('status') not in SYNC_STATUSES:return 'PENDING'
    if sync.get('signature') != fingerprint(take['video']['path'],take['audio']['path']):return 'PENDING'
    return sync['status']


def node_status(takes):
    """Aggregate: OK only if all existing pairs were confidently aligned.

    An unpaired take is incomplete; an empty node has status EMPTY.
    """
    states=[effective_status(t) for t in takes]
    if not states:return 'EMPTY'
    if all(s=='OK' for s in states):return 'OK'
    if 'KO' in states:return 'KO'
    if 'REVIEW' in states:return 'REVIEW'
    if 'PENDING' in states:return 'PENDING'
    return 'SINGLE'


def media_probe(path, ffprobe=None):
    if ffprobe is None:ffprobe=executables()[1]
    if not ffprobe:raise RuntimeError('ffprobe is not installed or not on PATH')
    p=subprocess.run([ffprobe,'-v','error','-show_streams','-show_format',
         '-of','json',str(path)],capture_output=True,text=True,timeout=25)
    if p.returncode:raise RuntimeError((p.stderr or 'ffprobe failed').strip()[:250])
    data=json.loads(p.stdout)
    streams=data.get('streams',[])
    v=next((x for x in streams if x.get('codec_type')=='video'),None)
    a=next((x for x in streams if x.get('codec_type')=='audio'),None)
    fmt=data.get('format',{})
    duration=float(fmt.get('duration') or (v or a or {}).get('duration') or 0)
    if not math.isfinite(duration) or duration<=0:raise RuntimeError('Media duration unavailable')
    rate=(v or {}).get('avg_frame_rate') or '0/0'
    try:
        n,d=map(int,rate.split('/')); fps=n/d if d else 0
    except (ValueError,ZeroDivisionError):fps=0
    return {'duration':duration,'video':bool(v),'audio':bool(a),
        'width':int(v.get('width') or 0) if v else 0,
        'height':int(v.get('height') or 0) if v else 0,
        'fps':fps,'channels':int(a.get('channels') or 0) if a else 0,
        'sample_rate':int(a.get('sample_rate') or 0) if a else 0}


def extract_audio(path, ffmpeg, seconds=MAX_SECONDS):
    args=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-i',str(path),
          '-t',str(seconds),'-map','0:a:0','-vn','-af','highpass=f=60,lowpass=f=320',
          '-ac','1','-ar',str(SAMPLE_RATE),'-f','f32le','pipe:1']
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=130)
    if p.returncode:raise RuntimeError((p.stderr.decode('utf-8',errors='replace') or 'ffmpeg failed').strip()[-350:])
    data=array.array('f');data.frombytes(p.stdout[:len(p.stdout)//4*4])
    if os.sys.byteorder!='little':data.byteswap()
    return data


def _fft(items, invert=False):
    """In-place radix-2 FFT fallback for installations without numpy."""
    from cmath import exp
    n=len(items);j=0
    for i in range(1,n):
        bit=n>>1
        while j&bit:j^=bit;bit>>=1
        j^=bit
        if i<j:items[i],items[j]=items[j],items[i]
    length=2
    while length<=n:
        angle=(2 if invert else -2)*math.pi/length
        wn=complex(math.cos(angle),math.sin(angle))
        for start in range(0,n,length):
            w=1+0j
            for k in range(start,start+length//2):
                a,b=items[k],items[k+length//2]*w
                items[k],items[k+length//2]=a+b,a-b
                w*=wn
        length*=2
    if invert:
        for i in range(n):items[i]/=n


def _correlation(video,audio):
    nv,na=len(video),len(audio)
    n=1<<(nv+na-2).bit_length()
    try:
        import numpy as np
        v=np.asarray(video,dtype=np.float32);a=np.asarray(audio,dtype=np.float32)
        # Remove DC offsets and gently compress extreme clipping.
        v=v-np.mean(v);a=a-np.mean(a)
        corr=np.fft.irfft(np.fft.rfft(a,n)*np.conj(np.fft.rfft(v,n)),n)
        return corr, v, a
    except ImportError:
        v=[float(x) for x in video];a=[float(x) for x in audio]
        vm=sum(v)/nv;am=sum(a)/na
        v=[x-vm for x in v];a=[x-am for x in a]
        fv=[complex(x,0) for x in v]+[0j]*(n-nv)
        fa=[complex(x,0) for x in a]+[0j]*(n-na)
        _fft(fv);_fft(fa)
        for i in range(n):fa[i]*=fv[i].conjugate()
        _fft(fa,True)
        return [x.real for x in fa],v,a


def estimate_offset(video,audio,max_offset_seconds=MAX_OFFSET_SECONDS):
    """Return offset in seconds, normalized peak correlation, and safe status."""
    v,a=list(video),list(audio)
    if min(len(v),len(a))<SAMPLE_RATE*MIN_OVERLAP_SECONDS:
        return None,0.,'KO','Audio too short for a reliable match'
    corr,v,a=_correlation(v,a)
    nv,na=len(v),len(a);n=len(corr)
    # Energy of valid overlapping segments for each possible lag.
    vp=[0.];ap=[0.]
    for x in v:vp.append(vp[-1]+x*x)
    for x in a:ap.append(ap[-1]+x*x)
    total_rms_v=math.sqrt(vp[-1]/nv)
    total_rms_a=math.sqrt(ap[-1]/na)
    if min(total_rms_v,total_rms_a)<0.00001:
        return None,0.,'KO','Audio is silent or too quiet'
    limit=min(max_offset_seconds*SAMPLE_RATE,max(nv,na)-SAMPLE_RATE*MIN_OVERLAP_SECONDS)
    best=(-1,None)
    scores=[]
    # Correlation positive lag means external recording begins earlier than video.
    for lag in range(-limit,limit+1):
        vi=max(0,-lag);ai=max(0,lag)
        length=min(nv-vi,na-ai)
        if length<MIN_OVERLAP_SECONDS*SAMPLE_RATE:continue
        e1=vp[vi+length]-vp[vi];e2=ap[ai+length]-ap[ai]
        if e1<=1e-10 or e2<=1e-10:continue
        score=float(corr[lag if lag>=0 else n+lag])/math.sqrt(e1*e2)
        if score>best[0]:best=(score,lag)
        if score>=0:scores.append((score,lag))
    score,lag=best
    if lag is None:return None,0.,'KO','No usable audio overlap'
    # Check a distinct competing lag (>=0.5s separation), not adjacent sample peaks.
    competition=max((s for s,l in scores if abs(l-lag)>SAMPLE_RATE//2),default=0.)
    if score>=0.30 and score-competition>=0.025:status='OK';err=''
    elif score>=0.15:status='REVIEW';err='Ambiguous or weak waveform match; verify by listening'
    else:status='KO';err='No reliable waveform match'
    return round(lag/SAMPLE_RATE,5) if status!='KO' else None,round(score,5),status,err


def synchronize(video_path,audio_path):
    signature=fingerprint(video_path,audio_path)
    ffmpeg,ffprobe=executables()
    if not ffmpeg or not ffprobe:
        return sync_record('KO',error='FFmpeg and ffprobe are required (install them and make them available on PATH)',signature=signature)
    try:
        pv=media_probe(video_path,ffprobe)
        pa=media_probe(audio_path,ffprobe)
        if not pv['video']:raise RuntimeError('Selected video has no video stream')
        if not pv['audio']:raise RuntimeError('Camera clip has no embedded audio track')
        if not pa['audio']:raise RuntimeError('Selected audio has no usable audio stream')
        v=extract_audio(video_path,ffmpeg)
        a=extract_audio(audio_path,ffmpeg)
        offset,score,status,error=estimate_offset(v,a)
        return sync_record(status,offset_seconds=offset,score=score,error=error,signature=signature)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        return sync_record('KO',error=str(exc),signature=signature)
