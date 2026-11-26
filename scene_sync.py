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
METHOD = 'multistage_waveform_v5'
SYNC_STATUSES = {'OK','REVIEW','KO','PENDING'}


def executables():
    """Use explicit overrides, then an installed system pair, then local FFmpeg.

    Managed tools live in the per-user profile and work without modifying PATH.
    """
    import scene_dependencies
    local = scene_dependencies.managed_executables()
    system_ffmpeg = shutil.which('ffmpeg')
    system_ffprobe = shutil.which('ffprobe')
    env_ffmpeg = os.environ.get('SCENESLATE_FFMPEG')
    env_ffprobe = os.environ.get('SCENESLATE_FFPROBE')
    if env_ffmpeg or env_ffprobe:
        ffmpeg = env_ffmpeg or system_ffmpeg or (local[0] if local else None)
        ffprobe = env_ffprobe or system_ffprobe or (local[1] if local else None)
        if ffmpeg and not ffprobe:
            sibling=Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
            if sibling.is_file():ffprobe=str(sibling)
        return ffmpeg, ffprobe
    if system_ffmpeg and system_ffprobe:
        return system_ffmpeg, system_ffprobe
    if local:
        return local
    return system_ffmpeg, system_ffprobe


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


def needs_sync_attention(take):
    """Only actual video + external-audio pairs can need synchronization.

    A one-sided take is intentional and should never inflate the review count.
    """
    return bool(take.get('video') and take.get('audio')) and effective_status(take) in (
        'KO', 'REVIEW', 'PENDING')


def node_status(takes):
    """Aggregate a subtree, treating intentional single-sided takes as complete.

    A node made only of single-sided takes displays SINGLE. Mixed OK and SINGLE
    displays OK; SINGLE/EMPTY are never review tasks.
    """
    states = [effective_status(t) for t in takes]
    if not states:
        return 'EMPTY'
    paired = [state for state in states if state != 'SINGLE']
    if not paired:
        return 'SINGLE'
    if 'KO' in paired:
        return 'KO'
    if 'REVIEW' in paired:
        return 'REVIEW'
    if 'PENDING' in paired:
        return 'PENDING'
    return 'OK'


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


def extract_audio(path, ffmpeg, seconds=MAX_SECONDS, *, rate=SAMPLE_RATE,
                  highpass=60, lowpass=320):
    args=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-i',str(path),
          '-t',str(seconds),'-map','0:a:0','-vn','-af',f'highpass=f={highpass},lowpass=f={lowpass}',
          '-ac','1','-ar',str(rate),'-f','f32le','pipe:1']
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


def _scored_lags(video, audio, rate, max_offset_seconds, overlap_seconds):
    """Peak-safe normalized cross-correlation for lags a(t+lag) vs v(t).

    A normalized dot product alone can strongly prefer short quiet overlaps;
    require both usable signal energy and a minimum effective overlap.
    """
    nv, na = len(video), len(audio)
    if min(nv, na) < overlap_seconds * rate:
        return []
    corr, v, a = _correlation(video, audio)
    n = len(corr)
    vp = [0.0]
    ap = [0.0]
    for value in v:
        vp.append(vp[-1] + value * value)
    for value in a:
        ap.append(ap[-1] + value * value)
    if min(vp[-1]/nv, ap[-1]/na) < 1.e-10:
        return []
    minimum = int(overlap_seconds * rate)
    limit = min(int(max_offset_seconds * rate), max(nv, na) - minimum)
    scores = []
    for lag in range(-limit, limit + 1):
        vi = max(0, -lag)
        ai = max(0, lag)
        length = min(nv - vi, na - ai)
        if length < minimum:
            continue
        e_v = vp[vi + length] - vp[vi]
        e_a = ap[ai + length] - ap[ai]
        if min(e_v, e_a) < 1.e-9:
            continue
        value = float(corr[lag if lag >= 0 else n + lag])/math.sqrt(e_v*e_a)
        # Inverted microphone polarity is a valid match.
        scores.append((abs(value), lag / rate))
    return scores


def _envelope(samples, hop=8, span=24):
    """Smoothed and compressed amplitude envelope (~100 Hz at 800 Hz).

    Log compression makes source/recorder gain differences less important.
    """
    values = [abs(float(v)) for v in samples]
    if not values:
        return []
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1]+value)
    output = []
    half = span//2
    for center in range(0, len(values), hop):
        low = max(0, center-half)
        high = min(len(values), center+half)
        amplitude = (prefix[high]-prefix[low])/(high-low)
        output.append(math.log1p(30*amplitude))
    return output


def _peak_candidates(scores, count=5, separation=0.22):
    """Pick well-separated potential lags, not neighbouring FFT bins."""
    candidates = []
    for score, offset in sorted(scores, reverse=True):
        if score < 0.06:
            break
        if all(abs(offset - existing[1]) > separation for existing in candidates):
            candidates.append((float(score), float(offset)))
            if len(candidates) >= count:
                break
    return candidates


def coarse_candidates(video, audio, max_offset_seconds=MAX_OFFSET_SECONDS):
    """Two independent coarse cues: signed waveform and signal envelope."""
    if min(len(video), len(audio)) < SAMPLE_RATE*MIN_OVERLAP_SECONDS:
        return []
    waveform = _peak_candidates(_scored_lags(video, audio, SAMPLE_RATE,
                            max_offset_seconds, MIN_OVERLAP_SECONDS), count=5)
    env_v = _envelope(video)
    env_a = _envelope(audio)
    envelope = _peak_candidates(_scored_lags(env_v, env_a, SAMPLE_RATE//8,
                            max_offset_seconds, MIN_OVERLAP_SECONDS), count=4)
    candidates = []
    for source, items in (('waveform', waveform), ('envelope', envelope)):
        for score, offset in items:
            for existing in candidates:
                if abs(offset-existing['offset']) < .12:
                    existing[source] = max(score, existing.get(source, 0.0))
                    if source == 'waveform':
                        existing['offset'] = offset
                    break
            else:
                candidates.append({'offset':offset,source:score})
    # Prefer candidates corroborated by both cues; still test good single-cue
    # matches since the camera and separate mic may have different spectra.
    candidates.sort(key=lambda entry: max(entry.get('waveform',0),
             entry.get('envelope',0))*0.8 + min(entry.get('waveform',0),
             entry.get('envelope',0))*0.2, reverse=True)
    return candidates[:5]


def estimate_offset(video, audio, max_offset_seconds=MAX_OFFSET_SECONDS):
    """Backward-compatible coarse estimate, without asserting subframe precision.

    For actual media, synchronize() additionally verifies short independent
    high-rate windows and returns a sub-millisecond-resolution offset.
    """
    if min(len(video),len(audio)) < SAMPLE_RATE*MIN_OVERLAP_SECONDS:
        return None,0.,'KO','Audio too short for a reliable match'
    if max(max(abs(float(x)) for x in video),max(abs(float(x)) for x in audio)) < 1.e-5:
        return None,0.,'KO','Audio is silent or too quiet'
    candidates = coarse_candidates(video,audio,max_offset_seconds)
    if not candidates:
        return None,0.,'KO','No usable audio overlap'
    best = candidates[0]
    score = max(best.get('waveform',0.),best.get('envelope',0.))
    competing = max((max(c.get('waveform',0.), c.get('envelope',0.))
                     for c in candidates[1:]), default=0.)
    # A coarse OK is not used as a final OK for actual files.
    if score >= .30 and score - competing >= .035:
        return round(best['offset'],5),round(score,5),'OK',''
    if score >= .19:
        return round(best['offset'],5),round(score,5),'REVIEW','Ambiguous or weak coarse match'
    return None,round(score,5),'KO','No reliable waveform match'


FINE_RATE = 8000
FINE_WINDOW_SECONDS = 2.4
FINE_SEARCH_SECONDS = 0.22


def _fine_window(video, audio, offset, v_start, seconds=FINE_WINDOW_SECONDS,
                 search=FINE_SEARCH_SECONDS, rate=FINE_RATE):
    """Estimate local lag from a full-overlap window, at 125-us granularity.

    Normalized FFT correlation is corroborated by spectral whitening
    (GCC-PHAT style) when NumPy is available. In the stdlib fallback, the
    standard FFT is used and a conservative confidence threshold applies.
    """
    n_samples = int(rate*seconds)
    v_index = int(round(v_start*rate))
    expected_a = v_index+int(round(offset*rate))
    margin = int(round(search*rate))
    a_start = expected_a-margin
    if v_index < 0 or a_start < 0 or v_index+n_samples > len(video) or a_start+n_samples+2*margin > len(audio):
        return None
    v = video[v_index:v_index+n_samples]
    a = audio[a_start:a_start+n_samples+2*margin]
    raw, v_adjusted, a_adjusted = _correlation(v,a)
    n = len(raw)
    # a window contains the entire video chunk throughout this search band.
    e_v = sum(float(q)*float(q) for q in v_adjusted)
    prefix = [0.0]
    for q in a_adjusted:
        prefix.append(prefix[-1]+float(q)*float(q))
    best = (-1.0,0,0.0)
    values = []
    for lag in range(2*margin+1):
        e_a = prefix[lag+n_samples]-prefix[lag]
        normalized = float(raw[lag])/math.sqrt(max(e_v*e_a,1.e-20))
        strength = abs(normalized)
        values.append(strength)
        if strength > best[0]:
            best = (strength,lag,normalized)
    score, lag, polarity = best
    if not math.isfinite(score) or score < 0.055:
        return None
    # Peak interpolation is stable only when its three samples form a true
    # concave peak and the magnitude of the refinement is at most 1 sample.
    delta=0.0
    if 0 < lag < len(values)-1:
        left,mid,right=values[lag-1:lag+2]
        denom=left-2*mid+right
        if denom < -1.e-10:
            delta=max(-0.5,min(0.5,.5*(left-right)/denom))
    independent=max((s for i,s in enumerate(values) if abs(i-lag)>rate//125),default=0.)
    phat_agreement=None
    band_votes=0
    try:
        import numpy as np
        vf=np.asarray(v_adjusted, dtype=np.float64)
        af=np.asarray(a_adjusted, dtype=np.float64)
        va=np.fft.rfft(vf,n)
        aa=np.fft.rfft(af,n)
        cross=aa*np.conj(va)
        # Partial spectral whitening: less sensitive to broadband noise than
        # pure PHAT and less sensitive to microphone EQ than raw correlation.
        weighted=cross/np.maximum(np.abs(cross),1.e-14)**0.70
        phat=np.abs(np.fft.irfft(weighted,n)[:2*margin+1])
        phat_lag=int(np.argmax(phat))
        phat_agreement=abs(phat_lag-lag)/rate
        # Independent frequency bands must locate the same delay. Reject bands
        # with negligible shared energy or a second comparable peak.
        frequencies=np.fft.rfftfreq(n,1/rate)
        for low,high in ((120,450),(450,1100),(1100,2300),(2300,3400)):
            mask=(frequencies>=low)&(frequencies<high)
            if not np.any(mask):continue
            if (np.sum(np.abs(va[mask])**2)<1e-4*np.sum(np.abs(va)**2)
                or np.sum(np.abs(aa[mask])**2)<1e-4*np.sum(np.abs(aa)**2)):continue
            band=np.abs(np.fft.irfft(np.where(mask,weighted,0),n)[:2*margin+1])
            peak=int(np.argmax(band));height=float(band[peak])
            if height<=1e-12:continue
            indices=np.arange(len(band))
            rival=float(np.max(np.where(np.abs(indices-peak)>rate*.008,band,0)))
            if abs(peak-lag)<=rate*.006 and rival<=height*.91:band_votes+=1
        if phat_agreement <= .008 and 0 < phat_lag < len(phat)-1:
            # Blend tiny adjustments only when both independent cues agree.
            lag=lag*.8+phat_lag*.2
    except ImportError:
        pass
    aligned_offset=(a_start+lag+delta-v_index)/rate
    return {'offset':aligned_offset,'score':min(1.,score),
            'peak_gap':score-independent,'phat_disagreement_s':phat_agreement,
            'start':v_start,'band_votes':band_votes,'polarity':-1 if polarity < 0 else 1}


def _fine_candidate(video, audio, offset, rate=FINE_RATE):
    total_v=len(video)/rate
    total_a=len(audio)/rate
    margin=FINE_SEARCH_SECONDS
    overlap_start=max(0.,-offset)+margin
    overlap_end=min(total_v,total_a-offset)-margin
    remaining=overlap_end-overlap_start-FINE_WINDOW_SECONDS
    if remaining < .01:
        return None
    # Search an energy-rich position within each chronological quarter. Plain
    # uniformly-spaced windows tend to land in long dialogue pauses and produce
    # unnecessary REVIEW results, even when the rest of the take is clear.
    starts=[]
    for quarter in range(4):
        choices=[overlap_start+remaining*(quarter+(step+.5)/4)/4
                 for step in range(4)]
        def energy(at):
            start_v=int(at*rate)
            start_a=int((at+offset)*rate)
            step=max(1,rate//200)
            sv=video[start_v:start_v+int(FINE_WINDOW_SECONDS*rate):step]
            sa=audio[start_a:start_a+int(FINE_WINDOW_SECONDS*rate):step]
            if not sv or not sa:
                return 0.
            ev=sum(float(x)*float(x) for x in sv)/len(sv)
            ea=sum(float(x)*float(x) for x in sa)/len(sa)
            return math.sqrt(max(0.,ev)*max(0.,ea))
        starts.append(max(choices,key=energy))
    windows=[_fine_window(video,audio,offset,start,rate=rate) for start in starts]
    windows=[w for w in windows if w is not None and w['score']>=.085]
    # Retry sparse evidence in shorter windows to avoid speech pauses.
    if len(windows)<2 and remaining>0.5:
        duration=max(.65,min(1.2,FINE_WINDOW_SECONDS/2))
        available=overlap_end-overlap_start-duration
        if available>duration:
            for i in range(5):
                start=overlap_start+available*i/4
                w=_fine_window(video,audio,offset,start,seconds=duration,rate=rate)
                if w and w['score']>=.12:windows.append(w)
            retained=[]
            for w in sorted(windows,key=lambda x:x['score'],reverse=True):
                if all(abs(w['start']-q['start'])>=duration for q in retained):retained.append(w)
            windows=retained
    if len(windows) < 2:
        return None
    values=sorted(w['offset'] for w in windows)
    # Prefer the strongest tight cluster over the median of several noisy peaks.
    clusters=[[w for w in windows if abs(w['offset']-seed['offset'])<=.010] for seed in windows]
    agree=max(clusters,key=lambda cluster:(len(cluster),sum(w['score'] for w in cluster)))
    mid=sum(w['offset']*w['score'] for w in agree)/sum(w['score'] for w in agree)
    agree=[w for w in windows if abs(w['offset']-mid)<=.012]
    outliers=[w for w in windows if abs(w['offset']-mid)>.012 and w['score']>=.16]
    if len(agree)<2:
        return {'status':'REVIEW','offset':mid,
                'score':sum(w['score'] for w in windows)/len(windows),
                'valid':len(agree),'window_count':len(windows),
                'spread_ms':(values[-1]-values[0])*1000,
                'error':'Independent windows disagree: possible repeated dialogue or clock drift'}
    # Consensus weighted by normalized correlation: do not let a single very
    # strong clapper dominate inconsistent speech later in the recording.
    points=sorted(agree,key=lambda w:w['offset'])
    weighted=sum(w['offset']*w['score'] for w in points)/sum(w['score'] for w in points)
    scores=sorted(w['score'] for w in agree)
    score=scores[len(scores)//2]
    spread=max(w['offset'] for w in agree)-min(w['offset'] for w in agree)
    phat=[w['phat_disagreement_s'] for w in agree if w['phat_disagreement_s'] is not None]
    phat_ok=not phat or sum(x<=.008 for x in phat)>=max(1,(len(phat)+1)//2)
    # Two or three very clean independent windows can provide stronger evidence
    # than four mediocre ones.  This reduces unnecessary REVIEW statuses without
    # lowering the bar for ambiguous/repetitive signals.
    unique_peaks=sum(1 for w in agree if w.get('peak_gap',0.) >= .045)
    very_clean=(len(agree)>=2 and score>=.43 and spread<=.004
                and unique_peaks>=2 and phat_ok and not outliers)
    consistent=(len(agree)>=3 and score>=.16 and spread<=.008
                and phat_ok and not outliers)
    # With highly consistent time-domain matches, PHAT disagreement from
    # microphone EQ should not force REVIEW when the peaks are unambiguous.
    eq_resilient=(len(agree)>=3 and score>=.32 and spread<=.004
                  and unique_peaks>=3 and not outliers)
    good=consistent or very_clean or eq_resilient
    return {'status':'OK' if good else 'REVIEW', 'offset':weighted,
            'score':score,'valid':len(agree),'window_count':len(windows),
            'spread_ms':spread*1000,
            'all_window_spread_ms':(values[-1]-values[0])*1000,
            'error':'' if good else 'Waveform alignment plausible; local matches need manual review',
            'precision_ms':1000/rate,
            'phat_ok':phat_ok,
            'consensus_windows':len(agree),
            'strong_unique_windows':unique_peaks,
            'multiband_windows':sum(w.get('band_votes',0)>=2 for w in agree),
            'temporal_span':max(w.get('start',0.) for w in agree)-min(w.get('start',0.) for w in agree),
            'outliers':len(outliers),
            'outlier_score':max((w['score'] for w in outliers),default=0.),
            'inlier_polarity_consistent':len({w.get('polarity',1) for w in agree})==1}


def spectral_lags(video, audio, rate=FINE_RATE, max_offset_seconds=MAX_OFFSET_SECONDS):
    """Signed, overlap-normalized correlation of multiband spectral changes.

    Independent of waveform polarity and mostly invariant to fixed microphone EQ.
    Returns (score, seconds), without a statistical probability interpretation.
    Inspired by audio feature cross-correlation and landmark alignment literature.
    """
    try:
        import numpy as np
    except ImportError:
        return []
    hop=max(1,rate//100); size=512
    def features(samples):
        x=np.asarray(samples,dtype=np.float32)
        if len(x)<size:return np.empty((0,12))
        frames=np.lib.stride_tricks.sliding_window_view(x,size)[::hop]
        power=np.abs(np.fft.rfft(frames*np.hanning(size),axis=1))**2
        freqs=np.fft.rfftfreq(size,1/rate)
        edges=(100,180,300,480,750,1150,1700,2400,3400)
        bands=[]
        for low,high in zip(edges,edges[1:]):
            val=np.mean(power[:,(freqs>=low)&(freqs<high)],axis=1)
            floor=max(float(np.percentile(val,15))*.25,1e-8)
            log=np.log(val+floor)
            # Temporal difference rejects stationary noise and fixed EQ;
            # slower difference complements short onset changes.
            for step in (1,4):
                d=log[4:]-log[4-step:len(log)-step]
                scale=max(float(np.std(d)),.1)
                d=np.clip(d/scale,-4,4)
                bands.append(d-np.mean(d))
        return np.asarray(bands,dtype=np.float64).T
    v,a=features(video),features(audio)
    nv,na=len(v),len(a); fps=rate/hop
    minimum=int(5*fps)
    if min(nv,na)<minimum:return []
    n=1<<(nv+na-2).bit_length()
    corr=np.fft.irfft(np.sum(np.fft.rfft(a,n,axis=0)*np.conj(np.fft.rfft(v,n,axis=0)),axis=1),n)
    vp=np.r_[0.,np.cumsum(np.sum(v*v,axis=1))];ap=np.r_[0.,np.cumsum(np.sum(a*a,axis=1))]
    lags=np.arange(-int(max_offset_seconds*fps),int(max_offset_seconds*fps)+1)
    vi=np.maximum(0,-lags);ai=np.maximum(0,lags);length=np.minimum(nv-vi,na-ai)
    good=length>=minimum;lags,vi,ai,length=[x[good] for x in (lags,vi,ai,length)]
    ev=vp[vi+length]-vp[vi];ea=ap[ai+length]-ap[ai]
    score=corr[lags%n]/np.sqrt(np.maximum(ev*ea,1e-20))
    # Require more than a small set of energetic onset frames.
    good=(ev>length*.1)&(ea>length*.1)
    return [(float(x),float(y/fps)) for x,y in zip(score[good],lags[good])]


def spectral_evidence(scores, offset):
    if not scores:return 0.,0.
    local=max((score for score,lag in scores if abs(lag-offset)<=.035),default=0.)
    rival=max((score for score,lag in scores if abs(lag-offset)>.09),default=0.)
    return local,local-rival


def robust_align(video_coarse, audio_coarse, video_fine, audio_fine,
                 max_offset_seconds=MAX_OFFSET_SECONDS, candidates=None):
    """Multiresolution consensus alignment; return a diagnostic record dict.

    The result is *not* a statistical probability. A candidate is called OK
    only when independent windows agree and no similar rival survives.
    """
    if candidates is None:
        candidates=coarse_candidates(video_coarse,audio_coarse,max_offset_seconds)
    candidates=[dict(c) for c in candidates]
    spectral=spectral_lags(video_fine,audio_fine,max_offset_seconds=max_offset_seconds)
    for strength,lag in _peak_candidates(spectral,count=3,separation=.12):
        if strength<.13:continue
        existing=next((c for c in candidates if abs(c['offset']-lag)<.10),None)
        if existing is None:candidates.append({'offset':lag,'spectral':strength})
        else:existing['spectral']=strength
    if not candidates:
        return {'status':'KO','offset':None,'score':0.,'error':'No usable coarse match'}
    results=[]
    for candidate in candidates:
        fine=_fine_candidate(video_fine,audio_fine,candidate['offset'])
        if fine is not None:
            fine['coarse_offset']=candidate['offset']
            fine['coarse_score']=max(candidate.get('waveform',0.),candidate.get('envelope',0.))
            # Reject coincidences that were never supported by the long signal.
            sp,margin=spectral_evidence(spectral,fine['offset'])
            fine['spectral_score']=sp;fine['spectral_margin']=margin
            fine['ranking']=fine['score']*.65+fine['coarse_score']*.20+max(0.,sp)*.15+min(fine['valid'],4)*.005
            # A second, globally unique spectral cue can rescue a weak waveform
            # decision, but only with precise independent fine-window agreement.
            if (fine['status']=='REVIEW' and fine['valid']>=3 and fine.get('spread_ms',999)<=8
                and fine['score']>=.12 and sp>=.28 and margin>=.13
                and fine.get('strong_unique_windows',0)>=2 and fine.get('temporal_span',0)>=2.4 and not fine.get('outliers',0)):
                fine['status']='OK';fine['error']=''
            # A distinctive global spectral or waveform alignment can justify OK
            # even when a quiet/noisy local window fails the fine verifier.
            # Require at least two temporally separated, tight waveform inliers,
            # and reject rival alignments, strong contradictions or drift.
            wave=candidate.get('waveform',0.)
            rival_wave=max((c.get('waveform',0.) for c in candidates
                            if abs(c['offset']-fine['offset'])>.09),default=0.)
            global_unique=(sp>=.20 and margin>=.075) or (wave>=.30 and wave-rival_wave>=.075)
            plausible=(fine['valid']>=2 and fine.get('spread_ms',999)<=10
                       and fine['score']>=.13 and fine.get('temporal_span',0)>=2.4
                       and fine.get('strong_unique_windows',0)>=2
                       and fine.get('outlier_score',1 if fine.get('outliers') else 0)<min(.24,fine['score']*.7)
                       and fine.get('inlier_polarity_consistent',True))
            # Stronger global spectral corroboration permits weak local peak
            # uniqueness, but still requires coherent fine estimates.
            spectral_rescue=(sp>=.32 and margin>=.13 and fine['valid']>=2
                and fine['score']>=.10 and fine.get('spread_ms',999)<=8
                and fine.get('temporal_span',0)>=2.4
                and fine.get('outlier_score',1 if fine.get('outliers') else 0)<.16
                and fine.get('inlier_polarity_consistent',True))
            # Global uniqueness and tight, temporally separated evidence can
            # override a PHAT veto or a weak contradictory window.
            corroborated=(fine['valid']>=2 and fine.get('spread_ms',999)<=10
                and fine.get('temporal_span',0)>=1.2 and fine['score']>=.10
                and sp>=.24 and margin>=.10
                and fine.get('outlier_score',1 if fine.get('outliers') else 0)<max(.18,fine['score']*.80)
                and fine.get('inlier_polarity_consistent',True))
            waveform_rescue=(fine['valid']>=2 and fine.get('spread_ms',999)<=6
                and fine.get('temporal_span',0)>=1.2 and fine['score']>=.20
                and fine.get('strong_unique_windows',0)>=2
                and wave>=.24 and wave-rival_wave>=.10
                and fine.get('outlier_score',1 if fine.get('outliers') else 0)<.16
                and fine.get('inlier_polarity_consistent',True))
            band_rescue=(fine['valid']>=2 and fine.get('multiband_windows',0)>=2
                and fine.get('spread_ms',999)<=8 and fine.get('temporal_span',0)>=1.2
                and fine['score']>=.11 and ((sp>=.17 and margin>=.065)
                    or (wave>=.19 and wave-rival_wave>=.09))
                and fine.get('outlier_score',1 if fine.get('outliers') else 0)<.18
                and fine.get('inlier_polarity_consistent',True))
            if fine['status']=='REVIEW' and ((global_unique and plausible) or spectral_rescue or corroborated or waveform_rescue or band_rescue):
                fine['status']='OK';fine['error']='';fine['decision']='global corroboration'
            results.append(fine)
    if not results:
        return {'status':'KO','offset':None,'score':0.,'error':'No coherent multiresolution match'}
    results.sort(key=lambda result:result['ranking'],reverse=True)
    best=results[0]
    # Matches at different lags must be clearly weaker. Otherwise repeated
    # dialogue/music makes confident automatic synchronization inappropriate.
    competing=next((item for item in results[1:] if abs(item['offset']-best['offset'])>.035),None)
    if competing and best['ranking']-competing['ranking']<.055 and not (best.get('spectral_score',0)>=.28 and best.get('spectral_margin',0)>=.12 and best['valid']>=2 and best.get('spread_ms',999)<=8 and abs(best['offset']-competing['offset'])>.09 and best.get('outlier_score',1 if best.get('outliers') else 0)<.16):
        best['status']='REVIEW'
        best['error']='Several plausible offsets; manual review recommended'
    best['offset']=round(best['offset'],6)
    best['score']=round(best['score'],5)
    return best


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
        candidates=coarse_candidates(v,a)
        vf=extract_audio(video_path,ffmpeg,seconds=MAX_SECONDS,rate=FINE_RATE,
                         highpass=110,lowpass=3400)
        af=extract_audio(audio_path,ffmpeg,seconds=MAX_SECONDS,rate=FINE_RATE,
                         highpass=110,lowpass=3400)
        refined=robust_align(v,a,vf,af,candidates=candidates)
        status=refined['status']
        record=sync_record(status,offset_seconds=refined.get('offset'),
                           score=refined.get('score'),error=refined.get('error',''),
                           signature=signature, method=METHOD)
        record['offset_resolution_ms']=refined.get('precision_ms')
        record['window_spread_ms']=refined.get('spread_ms')
        record['windows_verified']=refined.get('valid',0)
        record['coarse_offset_seconds']=refined.get('coarse_offset')
        record['coarse_score']=refined.get('coarse_score')
        record['candidate_count']=len(candidates)
        record['spectral_score']=refined.get('spectral_score')
        record['spectral_margin']=refined.get('spectral_margin')
        record['multiband_windows']=refined.get('multiband_windows',0)
        record['decision']=refined.get('decision','')
        record['decision']=refined.get('decision','local consensus')
        record['window_outliers']=refined.get('outliers',0)
        record['note']='Resolution is not accuracy. Validate important takes by ear; XML export rounds to timeline frames.'
        return record
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        return sync_record('KO',error=str(exc),signature=signature,
                           method=METHOD)
