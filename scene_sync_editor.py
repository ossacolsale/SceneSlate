"""Manual, non-destructive synchronization editor for SceneSlate.

Offset convention: external audio time at video time zero.  A positive value
means the recorder began before the camera.  Confirmation records the offset in
the catalog; media files never change.  All FFmpeg decoding happens off Tk.
"""
from __future__ import annotations

import array
import math
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
import tempfile
import time
from threading import Thread
import tkinter as tk
from tkinter import ttk, messagebox
import wave

import scene_sync
from scene_i18n import translate

WAVE_RATE = 2000
PREVIEW_RATE = 16000
MAX_WAVE_SECONDS = 240
PREVIEW_SECONDS = 20  # streaming-style chunks; automatically advance to video end
WAVE_WINDOW_SECONDS = 100  # bounded waveform cache, reloaded while scrolling


def _ffmpeg_pcm(path, start, seconds, rate, fmt, ffmpeg):
    """Decode a bounded exact-position mono fragment into signed PCM or floats."""
    if start < 0 or seconds <= 0 or seconds > MAX_WAVE_SECONDS:
        raise ValueError('Invalid audio preview interval')
    args=[str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin',
          '-ss',f'{start:.6f}','-i',str(path),'-map','0:a:0','-vn',
          '-t',f'{seconds:.6f}','-ac','1','-ar',str(rate),'-f',fmt,'pipe:1']
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=110)
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8',errors='replace')[-300:] or 'FFmpeg decoding failed')
    typecode='h' if fmt=='s16le' else 'f'
    a=array.array(typecode)
    sample_bytes=2 if typecode=='h' else 4
    a.frombytes(p.stdout[:len(p.stdout)//sample_bytes*sample_bytes])
    if sys.byteorder!='little':a.byteswap()
    return a


def _extract_preview(path, source_start, duration, ffmpeg, rate=PREVIEW_RATE):
    """Align a fragment to a common video clock, filling negative source time with silence."""
    count=max(1,round(duration*rate))
    pad=min(count,max(0,round(-source_start*rate)))
    result=array.array('h',[0])*count
    if pad==count:return result
    if source_start+duration <= 0:return result
    data=_ffmpeg_pcm(path,max(0,source_start),duration-pad/rate,rate,'s16le',ffmpeg)
    n=min(len(data),count-pad)
    result[pad:pad+n]=data[:n]
    return result


def render_preview_wav(video, external, offset, video_start, output_path, ffmpeg, *,
                       duration=PREVIEW_SECONDS, rate=PREVIEW_RATE, mode='split'):
    """Render a short stereo listening preview, never modifying the source media.

    split: camera in left channel, external audio in right; mix: both in both.
    camera / external: one signal in both channels.
    """
    if not math.isfinite(float(offset)) or not math.isfinite(float(video_start)):
        raise ValueError('Invalid preview offset or position')
    if video_start<0 or duration<=0 or duration>MAX_WAVE_SECONDS:
        raise ValueError('Invalid preview position')
    camera=_extract_preview(video,video_start,duration,ffmpeg,rate)
    audio=_extract_preview(external,video_start+offset,duration,ffmpeg,rate)
    samples=array.array('h')
    for c,a in zip(camera,audio):
        if mode=='split':left,right=c,a
        elif mode=='mix':left=right=round((c+a)/2)
        elif mode=='camera':left=right=c
        elif mode=='external':left=right=a
        else:raise ValueError('Unrecognized preview mode')
        samples.extend((max(-32768,min(32767,left)),max(-32768,min(32767,right))))
    if sys.byteorder!='little':samples.byteswap()
    with wave.open(str(output_path),'wb') as wav:
        wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return str(output_path)


def _play_wav(path):
    if sys.platform=='win32':
        import winsound
        winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
        return None
    for name,args in [('ffplay',['-nodisp','-autoexit','-hide_banner','-loglevel','error']),
                      ('paplay',[]),('aplay',['-q'])]:
        cmd=shutil.which(name)
        if cmd:
            return subprocess.Popen([cmd,*args,str(path)],stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    raise RuntimeError('No WAV player found: install ffplay, paplay or aplay')


class SyncEditor:
    """Modal waveform editor; callback is invoked only on explicit approval."""
    def __init__(self,parent,video,audio,record,on_approve,language='en'):
        self.parent=parent
        self.video=str(video);self.audio=str(audio)
        self.record=dict(record or {})
        self.on_approve=on_approve
        self.language=language
        self.offset=float(self.record.get('offset_seconds') or 0.)
        self.position=0.
        self.view_seconds=10.
        self.duration=min(MAX_WAVE_SECONDS,90.)
        self.wave_duration=self.duration
        self.full_duration=self.duration
        self.play_active=False
        self.play_timer=None
        self.play_cursor=0.
        self.play_chunk=PREVIEW_SECONDS
        self.playhead_seconds=0.
        self.play_chunk_start=0.
        self.play_chunk_length=0.
        self.play_wall_started=None
        self.cursor_timer=None
        self._programmatic_seek=False
        self.wave_camera_start=0.
        self.wave_external_start=0.
        self.wave_camera_range_end=0.
        self.wave_external_range_end=0.
        self.external_duration=0.
        self.wave_loading=False
        self.wave_job_token=0
        self.undo_offsets=[]
        self.redo_offsets=[]
        self.wave_camera=None;self.wave_external=None
        self.loading=True;self.closed=False;self.preview_process=None
        self.queue=Queue();self.generation=0
        self.tmp=tempfile.TemporaryDirectory(prefix='sceneslate-sync-preview-')
        self.win=tk.Toplevel(parent)
        self.win.title(self.tr('Manual synchronization editor'))
        self.win.configure(bg='#182336')
        self.win.transient(parent)
        self.win.minsize(740,540)
        self.win.geometry('1000x690')
        self.win.protocol('WM_DELETE_WINDOW',self.close)
        self._build()
        self.win.grab_set()
        self._schedule_job('load',self._load_waveforms)
        self.win.after(100,self._poll)
        self.win.after(200,self.draw)

    def tr(self,english):
        return translate(english,self.language)

    def _build(self):
        frame=ttk.Frame(self.win,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=self.tr('Compare camera and recorder audio'),font=('Segoe UI',15,'bold')).pack(anchor='w')
        ttk.Label(frame,text=f"{self.tr('Camera audio:')} {Path(self.video).name}").pack(anchor='w',pady=(6,0))
        ttk.Label(frame,text=f"{self.tr('External audio:')} {Path(self.audio).name}").pack(anchor='w')
        self.info=tk.StringVar(value=self.tr('Loading waveforms…'))
        ttk.Label(frame,textvariable=self.info).pack(anchor='w',pady=(7,2))
        ttk.Label(frame,text=self.tr('Upper: camera audio. Lower: external audio positioned using offset. Drag the lower waveform to adjust alignment.'),wraplength=930).pack(anchor='w')
        self.canvas=tk.Canvas(frame,height=245,background='#111c2b',highlightthickness=0,cursor='crosshair')
        self.canvas.pack(fill='both',expand=True,pady=(8,6))
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self._drag_press)
        self.canvas.bind('<B1-Motion>',self._drag_move)
        self.canvas.bind('<ButtonRelease-1>',self._drag_release)
        seek=ttk.Frame(frame);seek.pack(fill='x')
        ttk.Label(seek,text=self.tr('Position (video):')).pack(side='left')
        self.seek_value=tk.DoubleVar(value=0.)
        self.seek=ttk.Scale(seek,from_=0,to=80.,variable=self.seek_value,command=self._seek_changed)
        self.seek.pack(side='left',fill='x',expand=True,padx=8)
        self.seek_label=tk.StringVar(value='0.0 s')
        ttk.Label(seek,textvariable=self.seek_label,width=12).pack(side='right')
        self.playhead_label=tk.StringVar(value='▶ 0.00 s')
        ttk.Label(seek,textvariable=self.playhead_label,width=13).pack(side='right',padx=(4,8))
        line=ttk.Frame(frame);line.pack(fill='x',pady=(9,2))
        ttk.Label(line,text=self.tr('Visible interval:')).pack(side='left')
        self.zoom=tk.StringVar(value='10 s')
        combo=ttk.Combobox(line,textvariable=self.zoom,values=['2 s','5 s','10 s','20 s','30 s'],state='readonly',width=7)
        combo.pack(side='left',padx=7)
        combo.bind('<<ComboboxSelected>>',self._set_zoom)
        ttk.Label(line,text=self.tr('Offset (external source at video zero):')).pack(side='left',padx=(15,6))
        self.offset_var=tk.StringVar(value=f'{self.offset:+.3f}')
        entry=ttk.Entry(line,textvariable=self.offset_var,width=14)
        entry.pack(side='left')
        entry.bind('<Return>',self._parse_offset)
        entry.bind('<FocusOut>',self._parse_offset)
        ttk.Label(line,text='s').pack(side='left',padx=(3,5))
        row=ttk.Frame(frame);row.pack(fill='x',pady=(5,8))
        self.undo_button=ttk.Button(row,text=self.tr('↶ Undo'),command=self.undo)
        self.undo_button.pack(side='left',padx=(0,4))
        self.redo_button=ttk.Button(row,text=self.tr('↷ Redo'),command=self.redo)
        self.redo_button.pack(side='left',padx=(0,8))
        self.win.bind('<Control-z>',lambda e:(self.undo(),'break')[1])
        self.win.bind('<Control-y>',lambda e:(self.redo(),'break')[1])
        self.win.bind('<Control-Shift-Z>',lambda e:(self.redo(),'break')[1])
        self._refresh_history_buttons()
        ttk.Label(row,text=self.tr('Nudge:')).pack(side='left')
        for amount,label in [(-1.,'-1 s'),(-.1,'-100 ms'),(-.01,'-10 ms'),(-.001,'-1 ms'),
                             (.001,'+1 ms'),(.01,'+10 ms'),(.1,'+100 ms'),(1.,'+1 s')]:
            ttk.Button(row,text=label,command=lambda delta=amount:self._nudge(delta)).pack(side='left',padx=2)
        row2=ttk.Frame(frame);row2.pack(fill='x',pady=(2,5))
        ttk.Label(row2,text=self.tr('Listen:')).pack(side='left')
        self.listen_mode=tk.StringVar(value='split')
        listening=[('split',self.tr('Left camera / right recorder')),
                   ('mix',self.tr('Both mixed')),
                   ('camera',self.tr('Camera only')),
                   ('external',self.tr('Recorder only'))]
        for key,title in listening:
            ttk.Radiobutton(row2,text=title,variable=self.listen_mode,value=key).pack(side='left',padx=5)
        ttk.Button(row2,text=self.tr('▶ Play continuously'),command=self.play).pack(side='right',padx=4)
        ttk.Button(row2,text=self.tr('■ Stop'),command=self.stop).pack(side='right',padx=4)
        note=ttk.Label(frame,text=self.tr('Listen for echoes or doubled syllables. A manual OK confirms the current offset, not the whole recording (check drift on long takes).'),wraplength=930)
        note.pack(anchor='w',pady=(6,8))
        foot=ttk.Frame(frame);foot.pack(fill='x',pady=(8,0))
        ttk.Button(foot,text=self.tr('Cancel'),command=self.close).pack(side='right',padx=4)
        ttk.Button(foot,text=self.tr('✓ Confirm manual alignment'),command=self.confirm).pack(side='right',padx=4)
        suggested=self.record.get('offset_seconds')
        if suggested is not None:
            ttk.Button(foot,text=self.tr('Reset to suggested offset'),command=lambda:self._set_offset(float(suggested))).pack(side='left',padx=4)

        # Bind before ttk class handling so focused buttons do not double-toggle.
        def bind_space(widget):
            if not isinstance(widget,(ttk.Entry,tk.Entry,ttk.Combobox)):
                widget.bind('<KeyPress-space>',self.toggle_playback)
                widget.bind('<KeyRelease-space>',lambda e:'break')
            for child in widget.winfo_children():bind_space(child)
        bind_space(self.win)

    def _schedule_job(self,kind,func):
        def work():
            try:self.queue.put((kind,True,func()))
            except Exception as exc:self.queue.put((kind,False,str(exc)))
        Thread(target=work,name=f'SceneSlateSyncEditor-{kind}',daemon=True).start()

    def _load_waveforms(self):
        ffmpeg,ffprobe=scene_sync.executables()
        if not ffmpeg or not ffprobe:raise RuntimeError('FFmpeg/ffprobe not available')
        vinfo=scene_sync.media_probe(self.video,ffprobe)
        ainfo=scene_sync.media_probe(self.audio,ffprobe)
        if not vinfo['audio'] or not ainfo['audio']:
            raise RuntimeError('Both files must contain an audio stream')
        seconds=min(WAVE_WINDOW_SECONDS,float(vinfo['duration']))
        camera=_ffmpeg_pcm(self.video,0,seconds,WAVE_RATE,'f32le',ffmpeg)
        audio_start=max(0.,self.offset)
        audio_seconds=min(WAVE_WINDOW_SECONDS,max(0.,float(ainfo['duration'])-audio_start))
        recorder=(_ffmpeg_pcm(self.audio,audio_start,audio_seconds,WAVE_RATE,'f32le',ffmpeg)
                  if audio_seconds>0 else array.array('f'))
        return (camera,recorder,seconds,float(vinfo['duration']),
                float(ainfo['duration']),audio_start)

    def _request_wave_window(self):
        """Decode only a small surrounding window; never block Tk or load entire feature films."""
        if self.closed or self.loading or self.wave_loading or self.wave_camera is None:
            return
        left=self.position
        right=min(self.full_duration,self.position+self.view_seconds)
        source_left=left+self.offset
        source_right=right+self.offset
        # Missing source samples outside a real audio stream are intentional silence.
        audio_begin=max(0.,source_left)
        audio_end=min(self.external_duration,source_right)
        cam_ok=(left>=self.wave_camera_start and right<=self.wave_camera_range_end-2
                or right>=self.full_duration-0.001 and right<=self.wave_camera_range_end+0.001)
        aud_ok=(audio_end<=audio_begin or
                audio_begin>=self.wave_external_start and audio_end<=self.wave_external_range_end-2
                or audio_end>=self.external_duration-0.001 and
                audio_begin>=self.wave_external_start and audio_end<=self.wave_external_range_end+0.001)
        if cam_ok and aud_ok:return
        ffmpeg,_=scene_sync.executables()
        if not ffmpeg:return
        cam_start=max(0.,math.floor(left)-10.)
        cam_secs=min(WAVE_WINDOW_SECONDS,max(0.,self.full_duration-cam_start))
        aud_start=max(0.,cam_start+self.offset)
        aud_secs=min(WAVE_WINDOW_SECONDS,max(0.,self.external_duration-aud_start))
        token=self.wave_job_token=self.wave_job_token+1
        self.wave_loading=True
        def work():
            camera=(_ffmpeg_pcm(self.video,cam_start,cam_secs,WAVE_RATE,'f32le',ffmpeg)
                    if cam_secs>0 else array.array('f'))
            audio=(_ffmpeg_pcm(self.audio,aud_start,aud_secs,WAVE_RATE,'f32le',ffmpeg)
                   if aud_secs>0 else array.array('f'))
            return token,camera,audio,cam_start,cam_start+cam_secs,aud_start,aud_start+aud_secs
        self._schedule_job('wave',work)

    def _show_playhead(self):
        if self.closed or not self.canvas.winfo_exists():return
        self.canvas.delete('playhead')
        t=self.playhead_seconds
        if not self.position <= t <= self.position+self.view_seconds:return
        width=max(250,self.canvas.winfo_width())
        span=max(1,width-80)
        x=68+(t-self.position)*span/self.view_seconds
        self.canvas.create_line(x,10,x,max(180,self.canvas.winfo_height())-18,
              fill='#f7d16c',width=2,tags=('playhead',))
        label=f'{t:.2f} s'
        self.canvas.create_text(min(width-50,max(95,x+6)),14,text=label,
              fill='#ffe5a3',anchor='w',font=('Segoe UI',9,'bold'),tags=('playhead',))
        self.canvas.tag_raise('playhead')

    def _tick_playhead(self):
        self.cursor_timer=None
        if self.closed or not self.play_active:return
        if self.play_wall_started is not None:
            elapsed=max(0.,time.monotonic()-self.play_wall_started)
            self.playhead_seconds=min(self.full_duration,
                self.play_chunk_start+min(self.play_chunk_length,elapsed))
        self.playhead_label.set(f'▶ {self.playhead_seconds:.2f} s')
        old=self.position
        if self.playhead_seconds > self.position+self.view_seconds*.70:
            self.position=min(max(0.,self.full_duration-self.view_seconds),
                              max(0.,self.playhead_seconds-self.view_seconds*.70))
        if self.playhead_seconds < self.position:
            self.position=max(0.,self.playhead_seconds-self.view_seconds*.25)
        if abs(self.position-old)>.00001:
            self._programmatic_seek=True
            try:self.seek_value.set(self.position)
            finally:self._programmatic_seek=False
            self.seek_label.set(f'{self.position:.2f} s')
            self._request_wave_window()
            self.draw()
        else:
            self._show_playhead()
        self.cursor_timer=self.win.after(65,self._tick_playhead)

    def _poll(self):
        if self.closed:return
        try:
            while True:
                kind,ok,value=self.queue.get_nowait()
                if kind=='load':
                    self.loading=False
                    if ok:
                        if len(value)==6:
                            self.wave_camera,self.wave_external,self.wave_duration,self.full_duration,self.external_duration,self.wave_external_start=value
                        else:
                            self.wave_camera,self.wave_external,self.wave_duration=value[:3]
                            self.full_duration=value[3] if len(value)>3 else self.wave_duration
                            self.external_duration=self.full_duration
                            self.wave_external_start=0.
                        self.wave_camera_start=0.
                        self.wave_camera_range_end=self.wave_duration
                        self.wave_external_range_end=self.wave_external_start+min(WAVE_WINDOW_SECONDS,max(0.,self.external_duration-self.wave_external_start))
                        self.duration=self.full_duration
                        self.seek.configure(to=max(0.,self.duration-self.view_seconds))
                        self.info.set(self.tr('Waveforms ready. Drag recorder waveform or nudge the offset.'))
                        self.draw()
                    else:self.info.set(self.tr('Waveform loading failed:')+' '+value)
                elif kind=='wave':
                    self.wave_loading=False
                    if ok and value[0]==self.wave_job_token:
                        _,self.wave_camera,self.wave_external,self.wave_camera_start,self.wave_camera_range_end,self.wave_external_start,self.wave_external_range_end=value
                        self.draw()
                    elif not ok:
                        self.info.set(self.tr('Waveform loading failed:')+' '+str(value))
                elif kind=='preview':
                    if not ok:
                        self.info.set(self.tr('Preview failed:')+' '+str(value))
                        continue
                    serial,path,seconds=value
                    if serial != self.generation or not self.play_active:continue
                    try:
                        self._stop_output()
                        self.preview_process=_play_wav(path)
                        self.play_chunk_start=self.play_cursor-seconds
                        self.play_chunk_length=seconds
                        self.play_wall_started=time.monotonic()
                        self.playhead_seconds=self.play_chunk_start
                        self.info.set(self.tr('Playing synchronized audio. Press Stop to interrupt.'))
                        self.play_timer=self.win.after(max(1,int(seconds*1000)),
                                           lambda token=serial:self._play_next(token))
                    except (OSError,RuntimeError) as exc:
                        self.play_active=False
                        self.info.set(str(exc))
        except Empty:pass
        if not self.closed:self.win.after(100,self._poll)

    def _set_zoom(self,event=None):
        self.view_seconds=float(self.zoom.get().split()[0])
        self.seek.configure(to=max(0.,self.duration-self.view_seconds))
        self.position=min(self.position,max(0.,self.duration-self.view_seconds))
        self.seek_value.set(self.position);self._request_wave_window();self.draw()

    def _seek_changed(self,value):
        if self._programmatic_seek:return
        if self.play_active:self.stop()
        self.position=float(value)
        self.playhead_seconds=self.position
        self.playhead_label.set(f'▶ {self.playhead_seconds:.2f} s')
        self.seek_label.set(f'{self.position:.2f} s')
        self._request_wave_window();self.draw()

    def _parse_offset(self,event=None):
        try:
            value=float(self.offset_var.get().replace(',','.'))
            if not math.isfinite(value) or abs(value)>86400:raise ValueError
        except ValueError:
            self.offset_var.set(f'{self.offset:+.3f}')
            self.info.set(self.tr('Enter a finite offset in seconds.'))
            return
        self._set_offset(value)

    def _refresh_history_buttons(self):
        if hasattr(self,'undo_button'):
            self.undo_button.configure(state='normal' if self.undo_offsets else 'disabled')
            self.redo_button.configure(state='normal' if self.redo_offsets else 'disabled')

    def _set_offset(self,value,*,remember=True):
        new=round(float(value),6)
        if not math.isfinite(new) or abs(new)>86400:
            raise ValueError('Invalid offset')
        if new != self.offset:
            if remember:
                self.undo_offsets.append(self.offset)
                self.undo_offsets=self.undo_offsets[-150:]
                self.redo_offsets.clear()
            self.offset=new
        self.offset_var.set(f'{self.offset:+.3f}')
        self._refresh_history_buttons()
        self._request_wave_window()
        self.draw()

    def undo(self):
        if not self.undo_offsets:return
        previous=self.undo_offsets.pop()
        self.redo_offsets.append(self.offset)
        self._set_offset(previous,remember=False)

    def redo(self):
        if not self.redo_offsets:return
        next_offset=self.redo_offsets.pop()
        self.undo_offsets.append(self.offset)
        self._set_offset(next_offset,remember=False)

    def _nudge(self,delta):
        self._parse_offset()
        self._set_offset(self.offset+delta)

    def _drag_press(self,event):
        h=self.canvas.winfo_height()
        self.drag_start=(event.x,self.offset) if event.y>=h/2 else None
        if self.drag_start is None:
            width=max(1,self.canvas.winfo_width()-80)
            clicked=self.position+max(0,min(1,(event.x-68)/width))*self.view_seconds
            if self.play_active:self.stop()
            self.playhead_seconds=clicked
            self.playhead_label.set(f'▶ {clicked:.2f} s')
            self.position=max(0,min(self.duration-self.view_seconds,clicked-self.view_seconds/2))
            self.seek_value.set(self.position);self._request_wave_window();self.draw()

    def _drag_move(self,event):
        if not getattr(self,'drag_start',None):return
        x0,offset0=self.drag_start
        usable=max(1,self.canvas.winfo_width()-80)
        self._set_offset(offset0-(event.x-x0)*self.view_seconds/usable,remember=False)

    def _drag_release(self,event=None):
        original=getattr(self,'drag_start',None)
        self.drag_start=None
        if original and self.offset!=original[1]:
            self.undo_offsets.append(original[1])
            self.undo_offsets=self.undo_offsets[-150:]
            self.redo_offsets.clear()
            self._refresh_history_buttons()

    def draw(self):
        canvas=self.canvas
        if not canvas.winfo_exists():return
        canvas.delete('all')
        width=max(250,canvas.winfo_width());height=max(180,canvas.winfo_height())
        startx=68;endx=width-12;span=max(1,endx-startx)
        centers=(height*.28,height*.73)
        for i,kind in enumerate(('Camera','Recorder')):
            mid=centers[i]
            canvas.create_rectangle(startx,mid-48,endx,mid+48,outline='#324b65')
            canvas.create_line(startx,mid,endx,mid,fill='#34516c')
            canvas.create_text(8,mid,text=self.tr(kind),fill='#d8e7ff',anchor='w',font=('Segoe UI',9,'bold'))
        for n in range(6):
            x=startx+span*n/5
            canvas.create_line(x,12,x,height-15,fill='#263951',dash=(2,5))
            canvas.create_text(x,height-7,text=f'{self.position+self.view_seconds*n/5:.2f}',fill='#b8cae2',font=('Segoe UI',8))
        if self.wave_camera is None or self.wave_external is None:
            canvas.create_text(width/2,height/2,text=self.tr('Loading waveforms…'),fill='#8fadc8')
            self._show_playhead()
            return
        for idx,(samples,shift,color,wave_start) in enumerate(((self.wave_camera,0.,'#6db5e8',self.wave_camera_start),
                                                       (self.wave_external,self.offset,'#e6ba78',self.wave_external_start))):
            mid=centers[idx];total=len(samples)
            amps=[]
            for pixel in range(span):
                video_t=self.position+(pixel+.5)*self.view_seconds/span
                source_t=video_t+shift
                k0=max(0,int((source_t-wave_start-self.view_seconds/(span*2))*WAVE_RATE))
                k1=min(total,int((source_t-wave_start+self.view_seconds/(span*2))*WAVE_RATE)+1)
                if source_t<wave_start or k0>=total or k1<=k0:amps.append((0.,0.));continue
                window=samples[k0:k1]
                amps.append((min(window),max(window)))
            peak=max((max(abs(a),abs(b)) for a,b in amps),default=1.)
            gain=42/max(.001,peak)
            for pixel,(low,high) in enumerate(amps):
                if low==high==0:continue
                x=startx+pixel
                canvas.create_line(x,mid-high*gain,x,mid-low*gain,fill=color)
        self._show_playhead()

    def _stop_output(self):
        if sys.platform=='win32':
            try:
                import winsound
                winsound.PlaySound(None,winsound.SND_PURGE)
            except (OSError,ImportError,RuntimeError):pass
        if self.preview_process is not None:
            if self.preview_process.poll() is None:
                self.preview_process.terminate()
                try:self.preview_process.wait(timeout=.4)
                except subprocess.TimeoutExpired:self.preview_process.kill()
            self.preview_process=None

    def stop(self):
        self.play_active=False
        self.play_wall_started=None
        self.generation+=1   # Discard in-flight chunk rendering.
        if self.cursor_timer is not None:
            try:self.win.after_cancel(self.cursor_timer)
            except tk.TclError:pass
            self.cursor_timer=None
        if self.play_timer is not None:
            try:self.win.after_cancel(self.play_timer)
            except tk.TclError:pass
            self.play_timer=None
        self._stop_output()
        if not self.closed:self.info.set(self.tr('Playback stopped.'))

    def _play_next(self,serial):
        self.play_timer=None
        if self.closed or not self.play_active or serial!=self.generation:return
        self.play_wall_started=None
        self.playhead_seconds=min(self.full_duration,self.play_cursor)
        remaining=self.full_duration-self.play_cursor
        if remaining<=.002:
            self.stop()
            return
        ffmpeg,_=scene_sync.executables()
        if not ffmpeg:
            self.stop()
            self.info.set(self.tr('FFmpeg/ffprobe not available'))
            return
        start=self.play_cursor
        seconds=min(self.play_chunk,remaining)
        offset=self.offset;mode=self.listen_mode.get()
        self.play_cursor+=seconds
        path=str(Path(self.tmp.name)/f'preview-{serial}-{int(start*1000)}.wav')
        self.info.set(self.tr('Preparing listening preview…')+f' {start:.1f}s')
        def work():
            render_preview_wav(self.video,self.audio,offset,start,path,ffmpeg,
                               duration=seconds,mode=mode)
            return serial,path,seconds
        self._schedule_job('preview',work)

    def toggle_playback(self,event=None):
        # Do not interfere with text editing or a focused button's own Space action.
        if event is not None and isinstance(event.widget,(ttk.Entry,tk.Entry,ttk.Combobox)):
            return
        if self.play_active:self.stop()
        else:self.play()
        return 'break'

    def play(self):
        self._parse_offset()
        ffmpeg,_=scene_sync.executables()
        if not ffmpeg:
            messagebox.showerror(self.tr('Preview failed:'),self.tr('FFmpeg/ffprobe not available'),parent=self.win)
            return
        self.stop()
        self.play_active=True
        self.play_cursor=min(self.position,max(0.,self.full_duration))
        self.playhead_seconds=self.play_cursor
        self._tick_playhead()
        self._play_next(self.generation)

    def confirm(self):
        self._parse_offset()
        if not math.isfinite(self.offset):return
        if not messagebox.askyesno(self.tr('Confirm manual alignment'),
                self.tr('Save this offset as manually verified? Confirm only after listening to both tracks.'),
                parent=self.win):return
        try:self.on_approve(self.offset)
        except Exception as exc:
            messagebox.showerror(self.tr('Failed to save alignment'),str(exc),parent=self.win)
            return
        self.close()

    def close(self):
        if self.closed:return
        self.closed=True;self.generation+=1
        self.stop()
        try:self.win.grab_release()
        except tk.TclError:pass
        self.win.destroy()
        # Workers are daemon threads and cannot update Tk; an in-flight render
        # may still need the temporary directory, so cleanup is best-effort.
        try:self.tmp.cleanup()
        except OSError:pass
