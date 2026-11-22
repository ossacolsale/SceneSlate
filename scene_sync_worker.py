"""One daemon worker: never touches Tk or the mutable catalog off the UI thread."""
from __future__ import annotations
from queue import Queue, Empty
from threading import Thread
import json
import scene_sync


class SyncWorker:
    def __init__(self):
        self.input=Queue()
        self.output=Queue()
        self.active=set()
        self.closed=False
        self.thread=Thread(target=self._run,name='SceneSlateWaveformSync',daemon=True)
        self.thread.start()

    @staticmethod
    def key(video,audio):
        return json.dumps(scene_sync.fingerprint(video,audio),ensure_ascii=False)

    def submit(self,video,audio):
        if self.closed:return False
        key=self.key(video,audio)
        if key in self.active:return False
        self.active.add(key)
        self.input.put((key,video,audio))
        return True

    def _run(self):
        while True:
            item=self.input.get()
            if item is None:return
            key,video,audio=item
            try:result=scene_sync.synchronize(video,audio)
            except Exception as exc:result=scene_sync.sync_record('KO',error=str(exc),signature=scene_sync.fingerprint(video,audio))
            self.output.put((key,result))

    def receive(self):
        results=[]
        while True:
            try:
                key,result=self.output.get_nowait()
                self.active.discard(key)
                results.append((key,result))
            except Empty:return results

    def close(self):
        self.closed=True
        self.input.put(None)
