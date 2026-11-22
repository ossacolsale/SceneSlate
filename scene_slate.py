#!/usr/bin/env python3
"""SceneSlate: lightweight desktop footage logging for Windows and Linux."""
from __future__ import annotations

import copy
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import threading
import webbrowser
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, filedialog as _filedialog, messagebox as _messagebox, simpledialog as _simpledialog
from scene_i18n import LANGUAGES, translate

_ACTIVE_LANGUAGE = 'en'

class _TranslatedDialog:
    """Translate dialog-owned labels without touching filenames or user data."""
    def __init__(self, delegate): self._delegate=delegate
    def __getattr__(self, name):
        method=getattr(self._delegate,name)
        def call(*args,**kwargs):
            args=tuple(translate(a,_ACTIVE_LANGUAGE) if isinstance(a,str) else a for a in args)
            for key in ('title','message','detail'):
                if isinstance(kwargs.get(key),str): kwargs[key]=translate(kwargs[key],_ACTIVE_LANGUAGE)
            if 'filetypes' in kwargs:
                kwargs['filetypes']=[(translate(label,_ACTIVE_LANGUAGE), pattern) for label,pattern in kwargs['filetypes']]
            return method(*args,**kwargs)
        return call

filedialog = _TranslatedDialog(_filedialog)
messagebox = _TranslatedDialog(_messagebox)
simpledialog = _TranslatedDialog(_simpledialog)


import scene_core as core
import scene_session as session
import scene_sync
import scene_dependencies
from scene_sync_worker import SyncWorker
from scene_sync_editor import SyncEditor

APP_NAME = 'SceneSlate'
VIDEO = 'video'
AUDIO = 'audio'


def human_size(n):
    n = float(n)
    for unit in ('B','KB','MB','GB','TB'):
        if n < 1024 or unit == 'TB': return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def center_window(window, parent, width, height):
    window.geometry(f'{width}x{height}+{max(0,parent.winfo_rootx()+(parent.winfo_width()-width)//2)}+{max(0,parent.winfo_rooty()+(parent.winfo_height()-height)//2)}')


class FileBrowser(ttk.Frame):
    """Filesystem browser with sorting, orphan detection and restorable selection."""
    SORTS = {'Nome A → Z': 'name_asc', 'Nome Z → A': 'name_desc',
             'Data ↑ (meno recente)': 'created_asc', 'Data ↓ (più recente)': 'created_desc'}

    def __init__(self, master, app, kind):
        super().__init__(master, style='Panel.TFrame', padding=10)
        self.app = app
        self.kind = kind
        self.path = Path.home()
        self.drag_origin = None
        self.saved_selection = []
        self._suspend_refresh = True
        self.filter_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.all_var = tk.BooleanVar(value=False)
        self.sort_var = tk.StringVar(value='name_asc')
        self.sort_label_var = tk.StringVar(value='Nome A → Z')
        self.sort_picker = None
        self.only_unused_var = tk.BooleanVar(value=False)
        self.highlight_unused_var = tk.BooleanVar(value=True)
        self.recursive_var = tk.BooleanVar(value=False)
        self.count_var = tk.StringVar(value='')

        top = ttk.Frame(self, style='Panel.TFrame'); top.pack(fill='x')
        title = 'VIDEO  /  FILESYSTEM' if kind == VIDEO else 'AUDIO  /  FILESYSTEM'
        ttk.Label(top, text=title, style='Section.TLabel').pack(side='left')
        ttk.Button(top, text='Associa / abbina →', style='Primary.TButton', command=self.attach_selected).pack(side='right')

        bar = ttk.Frame(self, style='Panel.TFrame'); bar.pack(fill='x', pady=(7,4))
        ttk.Button(bar, text='↑', width=3, command=self.up).pack(side='left')
        ttk.Button(bar, text='Sfoglia…', command=self.browse).pack(side='left', padx=(5,6))
        entry = ttk.Entry(bar, textvariable=self.path_var)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda e:self.go_path())
        ttk.Button(bar, text='Vai', command=self.go_path).pack(side='left', padx=(5,0))
        ttk.Button(bar, text='⟳', width=3, command=self.refresh).pack(side='left', padx=(5,0))

        row = ttk.Frame(self, style='Panel.TFrame'); row.pack(fill='x', pady=(0,2))
        ttk.Label(row, text='Filtra:').pack(side='left')
        ttk.Entry(row, textvariable=self.filter_var, width=14).pack(side='left', padx=(5,8), fill='x', expand=True)
        ttk.Label(row, text='Ordina:').pack(side='left')
        sort_picker = ttk.Combobox(row, textvariable=self.sort_label_var, state='readonly', width=23,
                                   values=list(self.SORTS), style='Sort.TCombobox')
        self.sort_picker = sort_picker
        sort_picker.pack(side='left', padx=(5,0))
        self.sort_label_var.trace_add('write', self.on_sort_label)
        row2 = ttk.Frame(self, style='Panel.TFrame'); row2.pack(fill='x', pady=(0,4))
        ttk.Checkbutton(row2, text='Solo non associati', variable=self.only_unused_var,
                        command=self.settings_changed).pack(side='left', padx=(0,9))
        ttk.Checkbutton(row2, text='Evidenzia liberi', variable=self.highlight_unused_var,
                        command=self.settings_changed).pack(side='left', padx=(0,9))
        ttk.Checkbutton(row2, text='Sottocartelle', variable=self.recursive_var,
                        command=self.settings_changed).pack(side='left', padx=(0,9))
        ttk.Checkbutton(row2, text='Tutti i file', variable=self.all_var,
                        command=self.settings_changed).pack(side='left')

        tree_wrap = ttk.Frame(self, style='Panel.TFrame'); tree_wrap.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=('size','date','type'), show='tree headings',
                                 selectmode='extended', height=5)
        self.tree.heading('#0', text='Nome'); self.tree.column('#0', minwidth=135, width=205, stretch=True)
        self.tree.heading('size', text='Dimensione'); self.tree.column('size', minwidth=65, width=77, stretch=False, anchor='e')
        self.tree.heading('date', text='Creazione*'); self.tree.column('date', minwidth=116, width=125, stretch=False)
        self.tree.heading('type', text='Tipo'); self.tree.column('type', minwidth=44, width=53, stretch=False, anchor='center')
        self.tree.pack(side='left', fill='both', expand=True)
        sc = ttk.Scrollbar(tree_wrap, orient='vertical', command=self.tree.yview); sc.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=sc.set)
        self.tree.tag_configure('folder', foreground='#b9d7f6')
        self.tree.tag_configure('file', foreground='#edf3ff')
        self.tree.tag_configure('unused', foreground='#ffce78')
        self.tree.bind('<Double-1>', self.on_double_click)
        self.tree.bind('<Return>', self.on_enter)
        self.tree.bind('<ButtonPress-1>', self.drag_press, add='+')
        self.tree.bind('<B1-Motion>', self.drag_motion, add='+')
        self.tree.bind('<ButtonRelease-1>', self.drag_release, add='+')
        self.tree.bind('<<TreeviewSelect>>', self.on_selection)
        for event in ('<MouseWheel>', '<Button-4>', '<Button-5>', '<KeyRelease>'):
            self.tree.bind(event, lambda e:self.app.queue_save_session(), add='+')
        ttk.Label(self, textvariable=self.count_var, style='Muted.TLabel').pack(anchor='w', pady=(3,0))
        self.filter_var.trace_add('write', lambda *_:self.settings_changed())
        self._suspend_refresh = False
        self.navigate(self.path, update_catalog=False)

    def sort_labels(self):
        return {self.app.tr(label): mode for label, mode in self.SORTS.items()}

    def relabel(self):
        self._suspend_refresh = True
        labels = self.sort_labels()
        self.sort_picker.configure(values=list(labels))
        self.sort_label_var.set(next(k for k,v in labels.items() if v == self.sort_var.get()))
        self._suspend_refresh = False
        for col, original in (('#0','Nome'), ('size','Dimensione'), ('date','Creazione*'), ('type','Tipo')):
            self.tree.heading(col,text=self.app.tr(original))
        self.refresh()

    def on_sort_label(self, *_):
        mode = self.sort_labels().get(self.sort_label_var.get(), self.SORTS.get(self.sort_label_var.get()))
        if mode:
            self.sort_var.set(mode)
            self.settings_changed()

    def settings_changed(self):
        if not self._suspend_refresh:
            self.refresh()
            self.app.queue_save_session()

    def navigate(self, path, update_catalog=True):
        try:
            path = Path(path).expanduser().resolve()
            if not path.is_dir(): raise OSError('Non è una cartella.')
            # Permission check before changing the active location.
            with os.scandir(path) as scan: next(scan, None)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cartella non accessibile', str(exc), parent=self.app.root)
            return False
        if path != self.path:
            self.saved_selection = []
        self.path = path
        self.path_var.set(str(path))
        if update_catalog:
            self.app.catalog[f'{self.kind}_root'] = str(path)
            self.app.changed(record=False)
        self.refresh(preserve_scroll=False)
        self.app.queue_save_session()
        return True

    def up(self): self.navigate(self.path.parent)
    def go_path(self): self.navigate(self.path_var.get())
    def browse(self):
        d = filedialog.askdirectory(parent=self.app.root, title='Seleziona cartella '+self.kind,
                                     initialdir=str(self.path))
        if d: self.navigate(d)

    def _entries(self):
        if self.recursive_var.get():
            # Iterative os.walk: symlinks to directories are not followed.
            for root, _, files in os.walk(self.path, followlinks=False):
                for name in files:
                    p = Path(root) / name
                    try:
                        stat_info = p.stat()
                    except OSError:
                        stat_info = None
                    yield p, False, stat_info
        else:
            for p in self.path.iterdir():
                try:
                    isdir = p.is_dir()
                    stat_info = p.stat()
                except OSError:
                    continue
                yield p, isdir, stat_info

    def refresh(self, preserve_scroll=True):
        if not hasattr(self, 'tree'): return
        previous = list(self.tree.selection())
        if previous:
            self.saved_selection = [p for p in previous if Path(p).is_file()]
        scroll = self.tree.yview()[0] if preserve_scroll else 0.
        self.tree.delete(*self.tree.get_children())
        query = self.filter_var.get().casefold().strip()
        allowed = core.VIDEO_EXT if self.kind == VIDEO else core.AUDIO_EXT
        assigned = core.assigned_paths(self.app.catalog, self.kind)
        try:
            paths = core.sort_directory_entries(list(self._entries()), self.sort_var.get())
        except OSError as exc:
            self.count_var.set(self.app.tr(f'Impossibile leggere la cartella: {exc}'))
            return
        count = unused_count = 0
        for path, isdir, stat_info in paths:
            if not isdir:
                if not self.all_var.get() and path.suffix.lower() not in allowed: continue
                if query not in path.name.casefold(): continue
                unused = core.identity(path) not in assigned
                if self.only_unused_var.get() and not unused: continue
                unused_count += unused
            else:
                unused = False
            if stat_info is not None:
                timestamp, reliable = core.birth_timestamp(stat_info)
                date_text = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
                if not reliable: date_text += ' m'
                sz = '' if isdir else human_size(stat_info.st_size)
            else:
                date_text = '?' ; sz = '?'
            if isdir:
                display = '▸  ' + path.name
                tags = ('folder',)
            else:
                display = ('●  ' if unused and self.highlight_unused_var.get() else '    ')
                if self.recursive_var.get():
                    display += str(path.relative_to(self.path))
                else:
                    display += path.name
                tags = ('unused',) if unused and self.highlight_unused_var.get() else ('file',)
            self.tree.insert('', 'end', iid=str(path), text=display,
                             values=(sz, date_text, 'DIR' if isdir else path.suffix[1:].upper()), tags=tags)
            if not isdir: count += 1
        visible_saved = [p for p in self.saved_selection if self.tree.exists(p)]
        if visible_saved:
            self.tree.selection_set(visible_saved)
            self.tree.focus(visible_saved[0])
            self.tree.see(visible_saved[0])
        elif scroll and not self.saved_selection:
            self.tree.yview_moveto(scroll)
        note = ' · m = data modifica (creazione non disponibile)' if sys.platform != 'win32' else ''
        self.count_var.set(self.app.tr(f'{count} file · {unused_count} non associati · ● = libero{note}'))

    def selected_files(self):
        return [p for i in self.tree.selection() if (p := Path(i)).is_file()]

    def on_selection(self, event=None):
        if self.tree.selection():
            self.saved_selection = [p for p in self.tree.selection() if Path(p).is_file()]
        self.app.queue_save_session()

    def get_state(self):
        return dict(directory=str(self.path), filter=self.filter_var.get(), sort=self.sort_var.get(),
                    all_files=self.all_var.get(), only_unused=self.only_unused_var.get(),
                    highlight_unused=self.highlight_unused_var.get(), recursive=self.recursive_var.get(),
                    selected_files=list(self.saved_selection), scroll=self.tree.yview()[0])

    def restore_state(self, state, fallback_directory=None):
        state = state if isinstance(state, dict) else {}
        self._suspend_refresh = True
        self.filter_var.set(str(state.get('filter', '')))
        mode = state.get('sort', 'name_asc')
        if mode not in self.SORTS.values(): mode = 'name_asc'
        self.sort_var.set(mode)
        self.sort_label_var.set(next(k for k,v in self.sort_labels().items() if v == mode))
        for key,var in [('all_files',self.all_var), ('only_unused',self.only_unused_var),
                        ('highlight_unused',self.highlight_unused_var), ('recursive',self.recursive_var)]:
            var.set(bool(state.get(key, key == 'highlight_unused')))
        self.saved_selection = [str(p) for p in state.get('selected_files', []) if isinstance(p, str)]
        self._suspend_refresh = False
        directory = state.get('directory') or fallback_directory
        if not directory or not Path(directory).is_dir():
            directory = fallback_directory if fallback_directory and Path(fallback_directory).is_dir() else str(Path.home())
        if self.navigate(directory, update_catalog=False):
            self.saved_selection = [str(p) for p in state.get('selected_files', []) if isinstance(p, str)]
            self.refresh(preserve_scroll=False)
            if not any(self.tree.exists(p) for p in self.saved_selection):
                try: self.tree.yview_moveto(max(0., min(1., float(state.get('scroll', 0.)))))
                except (TypeError, ValueError): pass

    def attach_selected(self):
        paths = self.selected_files()
        if paths: self.app.attach_files(self.kind, paths)
        else: self.app.notice('Seleziona uno o più file, poi usa “Associa allo shot”.')

    def on_double_click(self,event):
        row = self.tree.identify_row(event.y)
        if not row: return
        p = Path(row)
        if p.is_dir(): self.navigate(p)
        elif p.is_file(): self.app.attach_files(self.kind,[p])

    def on_enter(self,event):
        items = self.tree.selection()
        if len(items) == 1 and Path(items[0]).is_dir(): self.navigate(items[0])
        else: self.attach_selected()

    def drag_press(self,event):
        row = self.tree.identify_row(event.y)
        self.drag_origin = (event.x_root,event.y_root,row) if row and Path(row).is_file() else None

    def drag_motion(self,event):
        if not self.drag_origin: return
        x,y,row = self.drag_origin
        if not self.app.dragging and abs(x-event.x_root)+abs(y-event.y_root)>9:
            selected = self.selected_files()
            if row not in [str(p) for p in selected]: selected = [Path(row)]
            if selected: self.app.start_drag(self.kind,selected,event.x_root,event.y_root)
        if self.app.dragging: self.app.drag_motion(event.x_root,event.y_root)

    def drag_release(self,event):
        if self.app.dragging: self.app.finish_drag(event.x_root,event.y_root)
        self.drag_origin = None


class SceneSlateApp:
    def __init__(self,root):
        self.root=root
        self.catalog=core.new_catalog()
        self.filepath=None
        self._session_dir=session.config_dir()
        self._session= session.read_state(self._session_dir)
        self._ffmpeg_prompt_suppressed = bool(self._session.get('ffmpeg_prompt_suppressed',False))
        self._ffmpeg_ask_var = tk.BooleanVar(value=not self._ffmpeg_prompt_suppressed)
        self._ffmpeg_installing = False
        self.language = self._session.get('language') if self._session.get('language') in LANGUAGES else 'en'
        global _ACTIVE_LANGUAGE
        _ACTIVE_LANGUAGE = self.language
        self.language_var = tk.StringVar(value=LANGUAGES[self.language])
        self._ui_labels = {}
        self._menu_labels = {}
        self._session_after_id=None
        self._ready=False
        self._restoring=False
        self.last_tree_selection=None
        self.active_side=VIDEO
        self.last_take_number=None
        self.copied_node=None
        self.undo_stack=[]
        self.dragging=None
        self.drag_popup=None
        self.changed_unsaved=False
        self._last_notice_raw='Pronto. Crea una scena, seleziona uno shot e trascinaci video o audio.'
        self.status_var=tk.StringVar(value=self.tr(self._last_notice_raw))
        self.notes_scene_var=tk.StringVar()
        self.notes_shot_var=tk.StringVar()
        self.notes_subshot_var=tk.StringVar()
        self.take_description_var=tk.StringVar()
        self.take_annotation_var=tk.StringVar()
        self._editing_node_target=None
        self._editing_take_target=None
        self.only_unsynced_var=tk.BooleanVar(value=False)
        self._sync_worker=SyncWorker()
        self._sync_timer=None
        self.only_empty_var=tk.BooleanVar(value=False)
        self.highlight_empty_var=tk.BooleanVar(value=True)
        self._updating=False
        self.make_styles()
        self.make_ui()
        self.localize_ui()
        self.shortcuts()
        self.refresh_scene_tree(select=None)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.bind('<Destroy>',self.on_root_destroy,add='+')
        self.root.minsize(1140,720)
        self.root.geometry('1550x890')
        self.root.title(APP_NAME+' — '+self.tr('Nuovo catalogo'))
        self.root.bind('<Configure>',lambda e:self.queue_save_session() if e.widget is self.root else None)
        self._ready=True
        self._sync_timer=self.root.after(400,self.poll_sync)

    def make_styles(self):
        self.root.configure(bg='#121a28')
        st=ttk.Style(self.root)
        if 'clam' in st.theme_names():st.theme_use('clam')
        self.bg='#121a28';self.panel='#1b2738';self.deep='#111b2b';self.fg='#edf3ff';self.muted='#a9bad0';self.accent='#497cae'
        st.configure('.',font=('Segoe UI',10),background=self.bg,foreground=self.fg)
        st.configure('Panel.TFrame',background=self.panel)
        st.configure('Root.TFrame',background=self.bg)
        st.configure('Panel.TLabel',background=self.panel,foreground=self.fg)
        st.configure('Muted.TLabel',background=self.panel,foreground=self.muted,font=('Segoe UI',9))
        st.configure('Section.TLabel',background=self.panel,foreground='#c3dfff',font=('Segoe UI',10,'bold'))
        st.configure('Title.TLabel',background=self.bg,foreground=self.fg,font=('Segoe UI',17,'bold'))
        st.configure('Sub.TLabel',background=self.bg,foreground=self.muted,font=('Segoe UI',10))
        st.configure('TButton',background='#2a405a',foreground=self.fg,padding=(9,6),borderwidth=0)
        st.map('TButton',background=[('active','#3b5675')],foreground=[('disabled','#75869d')])
        st.configure('Primary.TButton',background='#245c9a',foreground='#fff',padding=(9,6))
        st.map('Primary.TButton',background=[('active','#3175c0')])
        st.configure('Danger.TButton',background='#553244',foreground='#fff')
        st.map('Danger.TButton',background=[('active','#784153')])
        st.configure('TEntry',fieldbackground='#101b2a',foreground='#f5f9ff',insertcolor='white',bordercolor='#3c536d',padding=5)
        st.configure('Sort.TCombobox',fieldbackground='#182d44',background='#294764',foreground='#f1f6ff',arrowcolor='#f1f6ff')
        st.map('Sort.TCombobox',fieldbackground=[('readonly','#182d44')],
               foreground=[('readonly','#f1f6ff')],background=[('readonly','#294764')])
        st.configure('TCheckbutton',background=self.panel,foreground=self.fg)
        st.map('TCheckbutton',background=[('active',self.panel)])
        st.configure('Treeview',background=self.deep,fieldbackground=self.deep,foreground=self.fg,rowheight=28,bordercolor='#2c3f55',font=('Segoe UI',10))
        st.map('Treeview',background=[('selected','#345f91')],foreground=[('selected','#fff')])
        st.configure('Treeview.Heading',background='#283b51',foreground='#d8e9ff',font=('Segoe UI',9,'bold'),padding=(4,7))
        st.map('Treeview.Heading',background=[('active','#38506a')])
        st.configure('TPanedwindow',background=self.bg)
        st.configure('TSeparator',background='#33465e')

    def make_ui(self):
        header=ttk.Frame(self.root,style='Root.TFrame',padding=(18,12))
        header.pack(fill='x')
        title_frame=ttk.Frame(header,style='Root.TFrame');title_frame.pack(side='left')
        ttk.Label(title_frame,text='SceneSlate',style='Title.TLabel').pack(anchor='w')
        ttk.Label(title_frame,text='Catalogazione riprese  •  Associazioni video/audio  •  Export Resolve',style='Sub.TLabel').pack(anchor='w')
        actions=ttk.Frame(header,style='Root.TFrame');actions.pack(side='right')
        language_picker=ttk.Combobox(actions,textvariable=self.language_var,
                values=list(LANGUAGES.values()),state='readonly',width=10,style='Sort.TCombobox')
        language_picker.pack(side='right',padx=(4,0))
        self.tools_button=ttk.Menubutton(actions,text='Tools ▾')
        self.tools_menu=tk.Menu(self.tools_button,tearoff=False)
        self.tools_menu.add_command(label='FFmpeg setup…',command=lambda:self.ffmpeg_setup(manual=True))
        self.tools_menu.add_checkbutton(label='Ask at startup when FFmpeg is missing',
                       variable=self._ffmpeg_ask_var,command=self.set_ffmpeg_reminders)
        self.tools_menu.add_command(label='FFmpeg download website',command=lambda:webbrowser.open(scene_dependencies.SOURCE_PAGE))
        self.tools_button.configure(menu=self.tools_menu)
        self.tools_button.pack(side='right',padx=(8,0))
        ttk.Label(actions,text='Lingua:',style='Sub.TLabel').pack(side='right',padx=(12,0))
        language_picker.bind('<<ComboboxSelected>>',self.change_language)
        self.language_picker=language_picker
        for label,cmd in [('Nuovo',self.new_project),('Apri…',self.open_project),('Salva',self.save),('Salva con nome…',self.save_as),('Esporta…',self.export),('↶ Annulla',self.undo)]:
            ttk.Button(actions,text=label,command=cmd).pack(side='left',padx=3)
        paned=ttk.Panedwindow(self.root,orient='horizontal');paned.pack(fill='both',expand=True,padx=14,pady=(0,10))
        left=ttk.Frame(paned,style='Panel.TFrame',padding=12)
        right=ttk.Panedwindow(paned,orient='vertical')
        paned.add(left,weight=48);paned.add(right,weight=52)
        # Left: scene browser and assignments.
        head=ttk.Frame(left,style='Panel.TFrame');head.pack(fill='x')
        ttk.Label(head,text='SCENE / SHOT / INQUADRATURE',style='Section.TLabel').pack(side='left')
        ttk.Button(head,text='Convenzione…',command=self.settings).pack(side='right')
        controls=ttk.Frame(left,style='Panel.TFrame');controls.pack(fill='x',pady=(10,8))
        for text,action,sty in [('+ Scena',self.add_scene,'Primary.TButton'),('+ Shot',self.add_shot,'Primary.TButton'),('+ Sotto-shot',self.add_subshot,'Primary.TButton'),('− Elimina',self.delete_selected,'Danger.TButton'),('Rinumera…',self.renumber,'TButton')]:
            ttk.Button(controls,text=text,command=action,style=sty).pack(side='left',padx=(0,5))
        scene_wrap=ttk.Frame(left,style='Panel.TFrame');scene_wrap.pack(fill='both',expand=True)
        self.scene_tree=ttk.Treeview(scene_wrap,columns=('sync',),show='tree headings',selectmode='browse',height=5)
        self.scene_tree.heading('#0',text='Scene / shot / sub-shot')
        self.scene_tree.heading('sync',text='SYNC')
        self.scene_tree.column('#0',width=380,minwidth=200,stretch=True)
        self.scene_tree.column('sync',width=95,minwidth=78,stretch=False,anchor='center')
        self.scene_tree.pack(side='left',fill='both',expand=True)
        sc=ttk.Scrollbar(scene_wrap,command=self.scene_tree.yview);sc.pack(side='right',fill='y')
        self.scene_tree.config(yscrollcommand=sc.set)
        self.scene_tree.tag_configure('scene',foreground='#bcdbff')
        self.scene_tree.tag_configure('shot',foreground='#f3f6fd')
        self.scene_tree.tag_configure('subshot',foreground='#bcf5eb')
        self.scene_tree.tag_configure('empty_subshot',foreground='#ffce78')
        self.scene_tree.tag_configure('empty_scene',foreground='#ffbd73')
        self.scene_tree.tag_configure('empty_shot',foreground='#ffce78')
        self.scene_tree.tag_configure('sync_bad',foreground='#ffaf78')
        self.scene_tree.bind('<<TreeviewSelect>>',self.on_scene_select)
        self.scene_tree.bind('<Double-1>',lambda e:self.renumber())
        self.scene_tree.bind('<Delete>',lambda e:self.delete_selected())
        self.scene_tree.bind('<ButtonRelease-1>',self.drop_scene_release,add='+')
        self.scene_tree.bind('<Button-3>',self.show_scene_context)
        self.scene_context=tk.Menu(self.root,tearoff=False)
        self.scene_context.add_command(label='Copia contenuto  (Ctrl+C)',command=self.copy_selected)
        self.scene_context.add_command(label='Incolla qui  (Ctrl+V)',command=self.paste_selected)
        self.scene_context.add_separator()
        self.scene_context.add_command(label='Rinomina / Rinumera…',command=self.renumber)
        self.scene_context.add_command(label='Elimina…',command=self.delete_selected)
        copy_row=ttk.Frame(left,style='Panel.TFrame');copy_row.pack(fill='x',pady=(6,0))
        ttk.Button(copy_row,text='⧉ Copia contenuto',command=self.copy_selected).pack(side='left',padx=(0,5))
        ttk.Button(copy_row,text='↳ Incolla nella selezione',command=self.paste_selected).pack(side='left',padx=(0,5))
        ttk.Label(copy_row,text='Ctrl+C / Ctrl+V nella struttura',style='Muted.TLabel').pack(side='left')
        filter_row=ttk.Frame(left,style='Panel.TFrame');filter_row.pack(fill='x',pady=(6,0))
        ttk.Checkbutton(filter_row,text='Solo elementi senza file',variable=self.only_empty_var,
                        command=self.scene_filter_changed).pack(side='left',padx=(0,12))
        ttk.Checkbutton(filter_row,text='Evidenzia vuoti',variable=self.highlight_empty_var,
                        command=self.scene_filter_changed).pack(side='left')
        ttk.Checkbutton(filter_row,text='Solo non sincronizzati',variable=self.only_unsynced_var,
                        command=self.scene_filter_changed).pack(side='left',padx=(10,0))
        self.scene_count_var=tk.StringVar(value='')
        ttk.Label(left,textvariable=self.scene_count_var,style='Muted.TLabel').pack(anchor='w',pady=(3,0))

        detail_head=ttk.Frame(left,style='Panel.TFrame');detail_head.pack(fill='x',pady=(12,4))
        self.detail_label=ttk.Label(detail_head,text='CIAK E ABBINAMENTI',style='Section.TLabel');self.detail_label.pack(side='left')
        ttk.Button(detail_head,text='+ Ciak',command=self.new_take).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='↻ Sync',command=self.retry_sync).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='Sync details',command=self.sync_details).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='✎ Sync editor',command=self.edit_sync).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='N° ciak…',command=self.edit_take_number).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='↻ Auto',command=self.reset_take_number).pack(side='right',padx=(4,0))
        ttk.Button(detail_head,text='− Ciak',command=self.delete_take).pack(side='right',padx=(4,0))
        media_wrap=ttk.Frame(left,style='Panel.TFrame');media_wrap.pack(fill='both',expand=True)
        self.media_tree=ttk.Treeview(media_wrap,columns=('take','video','vq','audio','aq','sync'),
                                     show='headings',selectmode='browse',height=6)
        for col,title,width,minimum in [('take','Ciak',54,43),('video','VIDEO',165,84),
                                        ('vq','B/R/S',57,48),('audio','AUDIO',165,84),('aq','B/R/S',57,48),('sync','SYNC',91,75)]:
            self.media_tree.heading(col,text=title)
            self.media_tree.column(col,width=width,minwidth=minimum,stretch=col in ('video','audio'),
                                   anchor='center' if col in ('take','vq','aq','sync') else 'w')
        self.media_tree.tag_configure('paired',foreground='#e4f2ff')
        self.media_tree.tag_configure('unpaired',foreground='#ffce78')
        self.media_tree.tag_configure('missing',foreground='#f49b99')
        self.media_tree.tag_configure('sync_bad',foreground='#ffaf78')
        self.media_tree.pack(side='left',fill='both',expand=True)
        ms=ttk.Scrollbar(media_wrap,command=self.media_tree.yview);ms.pack(side='right',fill='y')
        self.media_tree.configure(yscrollcommand=ms.set)
        self.media_tree.bind('<Button-1>',self.media_click,add='+')
        self.media_tree.bind('<Double-1>',self.open_media)
        self.media_tree.bind('<Left>',lambda e:self.switch_side(VIDEO))
        self.media_tree.bind('<Right>',lambda e:self.switch_side(AUDIO))
        self.media_tree.bind('<Delete>',lambda e:self.remove_media())
        for key,quality in [('b','B'),('r','R'),('s','S'),('B','B'),('R','R'),('S','S')]:
            self.media_tree.bind(f'<KeyPress-{key}>',lambda e,q=quality:self.set_quality(q))
        self.media_tree.bind('<<TreeviewSelect>>',self.on_take_select)
        self.media_tree.bind('<ButtonRelease-1>',self.drop_scene_release,add='+')
        row=ttk.Frame(left,style='Panel.TFrame');row.pack(fill='x',pady=(7,4))
        self.side_var=tk.StringVar(value='Lato attivo: VIDEO')
        ttk.Button(row,text='← VIDEO',command=lambda:self.switch_side(VIDEO)).pack(side='left',padx=(0,3))
        ttk.Button(row,text='AUDIO →',command=lambda:self.switch_side(AUDIO)).pack(side='left',padx=(0,7))
        ttk.Label(row,textvariable=self.side_var,style='Section.TLabel').pack(side='left')
        ttk.Button(row,text='− File sul lato',command=self.remove_media).pack(side='right')
        r=ttk.Frame(left,style='Panel.TFrame');r.pack(fill='x',pady=(1,3))
        ttk.Label(r,text='Qualifica lato attivo:',style='Muted.TLabel').pack(side='left',padx=(0,8))
        for q,name in core.QUALITIES.items():
            ttk.Button(r,text=f'{q} · {name}',command=lambda q=q:self.set_quality(q)).pack(side='left',padx=2)
        ttk.Label(left,text='←/→ sceglie VIDEO o AUDIO; ↑/↓ sceglie il ciak; B/R/S cambia la qualifica. Trascina un file sulla riga per abbinarlo.',
                  style='Muted.TLabel',wraplength=550).pack(anchor='w')
        take_notes=ttk.Frame(left,style='Panel.TFrame');take_notes.pack(fill='x',pady=(8,0))
        ttk.Label(take_notes,text='Descrizione ciak:',style='Panel.TLabel').grid(row=0,column=0,sticky='w',pady=3)
        self.take_description=ttk.Entry(take_notes,textvariable=self.take_description_var)
        self.take_description.grid(row=0,column=1,sticky='ew',padx=7)
        ttk.Label(take_notes,text='Annotazioni ciak:',style='Panel.TLabel').grid(row=1,column=0,sticky='w',pady=3)
        self.take_annotation=ttk.Entry(take_notes,textvariable=self.take_annotation_var)
        self.take_annotation.grid(row=1,column=1,sticky='ew',padx=7)
        take_notes.columnconfigure(1,weight=1)
        for entry in (self.take_description,self.take_annotation):
            entry.bind('<FocusOut>',lambda e:self.commit_notes())
            entry.bind('<Return>',lambda e:self.commit_notes())
        n=ttk.Frame(left,style='Panel.TFrame');n.pack(fill='x',pady=(9,0))
        ttk.Label(n,text='Descrizione scena:',style='Panel.TLabel').grid(row=0,column=0,sticky='w',pady=3)
        self.scene_note=ttk.Entry(n,textvariable=self.notes_scene_var)
        self.scene_note.grid(row=0,column=1,sticky='ew',padx=7)
        ttk.Label(n,text='Descrizione shot:',style='Panel.TLabel').grid(row=1,column=0,sticky='w',pady=3)
        self.shot_note=ttk.Entry(n,textvariable=self.notes_shot_var)
        self.shot_note.grid(row=1,column=1,sticky='ew',padx=7)
        ttk.Label(n,text='Descrizione sotto-shot:',style='Panel.TLabel').grid(row=2,column=0,sticky='w',pady=3)
        self.subshot_note=ttk.Entry(n,textvariable=self.notes_subshot_var)
        self.subshot_note.grid(row=2,column=1,sticky='ew',padx=7)
        n.columnconfigure(1,weight=1)
        for entry in (self.scene_note,self.shot_note,self.subshot_note):
            entry.bind('<FocusOut>',lambda e:self.commit_notes())
            entry.bind('<Return>',lambda e:self.commit_notes())

        self.video_browser=FileBrowser(right,self,VIDEO)
        self.audio_browser=FileBrowser(right,self,AUDIO)
        right.add(self.video_browser,weight=1);right.add(self.audio_browser,weight=1)
        status=tk.Label(self.root,textvariable=self.status_var,anchor='w',bg='#0c1421',fg='#c8d7e9',font=('Segoe UI',9),padx=14,pady=8)
        status.pack(fill='x')

    def tr(self,message):
        return translate(message,self.language)

    def localize_ui(self):
        """Relabel existing widgets in place: changing language never loses focus, media or edits."""
        def visit(widget):
            try:
                current = widget.cget('text')
                if widget not in self._ui_labels:
                    self._ui_labels[widget] = current
                widget.configure(text=self.tr(self._ui_labels[widget]))
            except (tk.TclError,AttributeError,KeyError):
                pass
            if isinstance(widget,tk.Menu):
                try:
                    for i in range(widget.index('end')+1):
                        if widget.type(i) not in ('command','cascade','checkbutton','radiobutton'): continue
                        key=(widget,i)
                        if key not in self._menu_labels:
                            self._menu_labels[key]=widget.entrycget(i,'label')
                        widget.entryconfigure(i,label=self.tr(self._menu_labels[key]))
                except (tk.TclError,TypeError): pass
            for child in widget.winfo_children():visit(child)
        visit(self.root)
        visit(self.scene_context)
        visit(self.tools_menu)
        for browser in (self.video_browser,self.audio_browser): browser.relabel()
        self.media_tree.heading('take',text=self.tr('Ciak'))
        self.media_tree.heading('vq',text='B/R/S')
        self.media_tree.heading('aq',text='B/R/S')
        self.media_tree.heading('sync',text='SYNC')
        self.scene_tree.heading('#0',text=self.tr('Scene / shot / sub-shot'))
        self.scene_tree.heading('sync',text='SYNC')
        self.scene_count_var.set(self.tr(self.scene_count_var.get()))
        self.side_var.set(self.tr('Lato attivo: ')+self.active_side.upper())
        self.status_var.set(self.tr(self._last_notice_raw))
        self.update_title()
        # Scene tree / take headings are generated for the currently selected node.
        self.refresh_scene_tree()

    def change_language(self,event=None):
        new = next((k for k,v in LANGUAGES.items() if v == self.language_var.get()),'en')
        if new == self.language:return
        self.commit_notes()
        self.language=new
        global _ACTIVE_LANGUAGE
        _ACTIVE_LANGUAGE=new
        self.localize_ui()
        self.queue_save_session()


    def set_ffmpeg_reminders(self):
        self._ffmpeg_prompt_suppressed = not self._ffmpeg_ask_var.get()
        self.queue_save_session()

    def maybe_prompt_ffmpeg(self):
        """Ask on each launch if both tools are not found, unless suppressed."""
        if self._ffmpeg_prompt_suppressed or self._ffmpeg_installing:return
        if not all(scene_sync.executables()):
            self.ffmpeg_setup(manual=False)

    def ffmpeg_setup(self, manual=False):
        """The consent dialog has no network side effects; install only on click."""
        if self._ffmpeg_installing:return
        binaries=scene_sync.executables()
        if all(binaries):
            if manual:
                messagebox.showinfo(self.tr('FFmpeg is ready'),
                    self.tr('Both required tools are available:')+'\n\n'+str(binaries[0])+'\n'+str(binaries[1]),
                    parent=self.root)
            return
        dialog=tk.Toplevel(self.root)
        dialog.title(self.tr('Set up FFmpeg'))
        dialog.configure(bg=self.panel)
        dialog.transient(self.root)
        frame=ttk.Frame(dialog,style='Panel.TFrame',padding=18)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=self.tr('FFmpeg and ffprobe are missing.'),
                  style='Section.TLabel').pack(anchor='w',pady=(0,10))
        if sys.platform == 'win32':
            explanation=self.tr('SceneSlate can download the Windows essentials build from gyan.dev (linked by ffmpeg.org), verify its published SHA-256 checksum, and install ffmpeg.exe and ffprobe.exe into your user profile. No administrator access or PATH changes are needed. The download is approximately 100–150 MB. No media files will be changed.')
        else:
            explanation=self.tr('Automatic installation is currently supported on Windows. On Linux install FFmpeg using your package manager (for example: sudo apt install ffmpeg) and restart SceneSlate.')
        ttk.Label(frame,text=explanation,style='Panel.TLabel',wraplength=465,
                  justify='left').pack(anchor='w',fill='x',pady=(0,12))
        dont_ask=tk.BooleanVar(value=self._ffmpeg_prompt_suppressed)
        ttk.Checkbutton(frame,text=self.tr('Do not ask again at startup'),variable=dont_ask).pack(anchor='w',pady=(0,12))
        footer=ttk.Frame(frame,style='Panel.TFrame');footer.pack(fill='x')
        def save_preference():
            self._ffmpeg_prompt_suppressed = bool(dont_ask.get())
            self._ffmpeg_ask_var.set(not self._ffmpeg_prompt_suppressed)
            self.queue_save_session()
        def dismiss():
            save_preference();dialog.destroy()
        def install():
            save_preference();dialog.destroy();self.install_ffmpeg_windows()
        ttk.Button(footer,text=self.tr('Later'),command=dismiss).pack(side='right',padx=(5,0))
        if sys.platform == 'win32':
            ttk.Button(footer,text=self.tr('Download and install'),command=install,
                       style='Primary.TButton').pack(side='right')
        else:
            ttk.Button(footer,text=self.tr('Open FFmpeg website'),
                  command=lambda:webbrowser.open('https://ffmpeg.org/download.html')).pack(side='right')
        center_window(dialog,self.root,530,300)
        dialog.protocol('WM_DELETE_WINDOW',dismiss)
        dialog.grab_set()

    def install_ffmpeg_windows(self):
        """Background installation: Tk is touched only in the polling callback."""
        if sys.platform != 'win32' or self._ffmpeg_installing:return
        self._ffmpeg_installing=True
        events=Queue()
        cancelled=threading.Event()
        dialog=tk.Toplevel(self.root)
        dialog.title(self.tr('Installing FFmpeg'))
        dialog.configure(bg=self.panel)
        dialog.transient(self.root)
        frame=ttk.Frame(dialog,style='Panel.TFrame',padding=18)
        frame.pack(fill='both',expand=True)
        progress_label=tk.StringVar(value=self.tr('Connecting to the download server…'))
        ttk.Label(frame,textvariable=progress_label,style='Panel.TLabel',wraplength=450).pack(fill='x',pady=(0,12))
        bar=ttk.Progressbar(frame,length=400,mode='indeterminate');bar.pack(fill='x',pady=(0,12))
        bar.start(12)
        def cancel():
            cancelled.set()
            cancel_button.configure(state='disabled')
            progress_label.set(self.tr('Cancelling download…'))
        cancel_button=ttk.Button(frame,text=self.tr('Cancel'),command=cancel)
        cancel_button.pack(side='right')
        center_window(dialog,self.root,510,170)
        dialog.protocol('WM_DELETE_WINDOW',cancel)
        dialog.grab_set()
        def background():
            try:
                installed=scene_dependencies.install_windows(
                    callback=lambda phase,done,total:events.put(('progress',phase,done,total)),
                    cancel=cancelled)
                events.put(('done',installed))
            except Exception as exc:
                events.put(('error',str(exc)))
        threading.Thread(target=background,name='SceneSlateFFmpegInstaller',daemon=True).start()
        def poll():
            if not dialog.winfo_exists():return
            terminal=None
            while True:
                try: event=events.get_nowait()
                except Empty:break
                if event[0]=='progress':
                    _,phase,done,total=event
                    if phase=='checksum':progress_label.set(self.tr('Checking the vendor SHA-256 checksum…'))
                    elif phase=='download':
                        if total:
                            bar.stop();bar.configure(mode='determinate',maximum=total,value=done)
                            progress_label.set(self.tr('Downloading FFmpeg:')+f' {done/(1024*1024):.1f} / {total/(1024*1024):.1f} MB')
                        else:progress_label.set(self.tr('Downloading FFmpeg:')+f' {done/(1024*1024):.1f} MB')
                    elif phase=='extract':progress_label.set(self.tr('Verifying and extracting the executables…'))
                else:terminal=event
            if terminal is not None:
                bar.stop();dialog.grab_release();dialog.destroy()
                self._ffmpeg_installing=False
                if terminal[0]=='done':
                    self.recover_missing_ffmpeg_sync()
                    self.schedule_sync()
                    messagebox.showinfo(self.tr('FFmpeg installed'),
                        self.tr('FFmpeg and ffprobe are now ready. Previously blocked synchronization attempts will be retried.'),parent=self.root)
                elif not cancelled.is_set():
                    messagebox.showerror(self.tr('FFmpeg installation failed'),terminal[1],parent=self.root)
                return
            self.root.after(150,poll)
        self.root.after(150,poll)

    def recover_missing_ffmpeg_sync(self):
        """Reprocess only KO takes caused solely by missing tools."""
        if not all(scene_sync.executables()):return 0
        count=0
        for _scene,_shot,_sub,container in core.iter_containers(self.catalog):
            for take in container['takes']:
                sync=take.get('sync') or {}
                if sync.get('status') != 'KO':continue
                error=str(sync.get('error','')).lower()
                if ('ffmpeg' in error or 'ffprobe' in error) and any(
                        part in error for part in ('required','not installed','not on path','not found')):
                    take['sync']=None
                    count+=1
        if count:
            self.changed()
            self.refresh_scene_tree()
        return count

    def shortcuts(self):
        self.root.bind_all('<Control-s>',lambda e:self.save())
        self.root.bind_all('<Control-o>',lambda e:self.open_project())
        self.root.bind_all('<Control-n>',lambda e:self.new_project())
        self.root.bind_all('<Control-z>',lambda e:self.undo())
        self.root.bind_all('<Control-c>',self.copy_shortcut)
        self.root.bind_all('<Control-v>',self.paste_shortcut)

    def notice(self,message):
        self._last_notice_raw=message
        self.status_var.set(self.tr(message))

    def queue_save_session(self):
        if not self._ready or self._restoring:return
        if self._session_after_id is not None:
            try:self.root.after_cancel(self._session_after_id)
            except tk.TclError:pass
        self._session_after_id=self.root.after(450,self.save_session)

    def session_data(self):
        selected=self.scene_tree.selection()
        if selected:self.last_tree_selection=selected[0]
        return {'version':4, 'language':self.language,
                'ffmpeg_prompt_suppressed':self._ffmpeg_prompt_suppressed, 'last_catalog':str(self.filepath) if self.filepath else None,
                'selected_scene_shot':self.last_tree_selection,
                'selected_take':self.last_take_number,'active_side':self.active_side,
                'only_empty':self.only_empty_var.get(),
                'only_unsynced':self.only_unsynced_var.get(),
                'highlight_empty':self.highlight_empty_var.get(),
                'video':self.video_browser.get_state(),
                'audio':self.audio_browser.get_state(),
                'scene_scroll':self.scene_tree.yview()[0],
                'geometry':self.root.geometry()}

    def save_session(self):
        self._session_after_id=None
        if not self._ready or self._restoring:return
        try:session.write_state(self.session_data(),self._session_dir)
        except OSError as exc:self.notice(f'Impossibile salvare le preferenze di sessione: {exc}')

    def _remove_draft(self):
        for draft in (session.draft_file(self._session_dir), session.legacy_draft_file(self._session_dir)):
            try:draft.unlink(missing_ok=True)
            except OSError:pass

    def startup(self, explicit_project=None):
        """Prefer CLI project, then previous catalog, then autosaved unnamed draft."""
        state=self._session
        self._restoring=True
        desired=explicit_project or state.get('last_catalog')
        loaded=False
        if desired:
            try:
                self.catalog=core.load_catalog(desired)
                self.filepath=str(Path(desired).resolve())
                loaded=True
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self.notice(f'Ultimo catalogo non disponibile: {exc}')
        if not loaded and not explicit_project:
            draft = next((p for p in (session.draft_file(self._session_dir), session.legacy_draft_file(self._session_dir)) if p.is_file()), None)
            if draft is not None and not state.get('last_catalog'):
                try:
                    self.catalog=core.load_catalog(draft)
                    self.filepath=None
                    self.changed_unsaved=True
                    loaded=True
                except (OSError,ValueError,KeyError,TypeError):pass
        self.only_empty_var.set(bool(state.get('only_empty',False)))
        self.only_unsynced_var.set(bool(state.get('only_unsynced',False)))
        self.highlight_empty_var.set(bool(state.get('highlight_empty',True)))
        geometry=state.get('geometry','')
        if isinstance(geometry,str) and geometry:
            try:self.root.geometry(geometry)
            except tk.TclError:pass
        for kind,browser in ((VIDEO,self.video_browser),(AUDIO,self.audio_browser)):
            browser.restore_state(state.get(kind),self.catalog.get(f'{kind}_root'))
        self.active_side=state.get('active_side',VIDEO) if state.get('active_side') in (VIDEO,AUDIO) else VIDEO
        self.last_take_number=state.get('selected_take') if isinstance(state.get('selected_take'),int) else None
        selected=state.get('selected_scene_shot')
        if isinstance(selected,str):self.last_tree_selection=selected
        self.refresh_scene_tree(select=selected)
        self.update_title()
        self._restoring=False
        self.queue_save_session()
        self.recover_missing_ffmpeg_sync()
        self.schedule_sync()
        if loaded:
            self.notice('Sessione ripristinata: '+(Path(self.filepath).name if self.filepath else 'bozza autosalvata'))

    def scene_filter_changed(self):
        if self.only_unsynced_var.get() and self.only_empty_var.get():
            # These filters describe competing workflows. Unsynced takes take precedence.
            self.only_empty_var.set(False)
        self.refresh_scene_tree()
        self.queue_save_session()

    def snapshot(self):
        self.undo_stack.append(copy.deepcopy(self.catalog))
        if len(self.undo_stack)>35:self.undo_stack.pop(0)

    def changed(self,record=True):
        self.changed_unsaved=True
        self.update_title()
        target=self.filepath or session.draft_file(self._session_dir)
        try:
            core.save_catalog(self.catalog,target)
            if self.filepath:self.changed_unsaved=False
            self.update_title()
        except (OSError,core.CatalogError) as exc:
            self.notice(f'Attenzione: salvataggio automatico non riuscito: {exc}')
        if hasattr(self,'video_browser'):
            self.video_browser.refresh()
            self.audio_browser.refresh()
        self.queue_save_session()

    def update_title(self):
        path=Path(self.filepath).name if self.filepath else self.tr('Senza nome')
        self.root.title(f'{APP_NAME} — {path}' + (' *' if self.changed_unsaved else ''))

    def selected_ids(self):
        sel=self.scene_tree.selection()
        if not sel:return None,None
        parts=sel[0].split(':')
        if parts[0]=='s':return int(parts[1]),None
        if parts[0] in ('t','u'):return int(parts[1]),int(parts[2])
        return None,None

    def selected_subshot_id(self):
        selection=self.scene_tree.selection()
        if selection and selection[0].startswith('u:'):
            return selection[0].split(':',3)[3]
        return None

    def active_target(self,quiet=False):
        target=self.active_shot(quiet)
        return (*target,self.selected_subshot_id()) if target else None

    def tree_target(self):
        n,h=self.selected_ids()
        return (n,h,self.selected_subshot_id()) if n is not None else None

    def copy_selected(self):
        target=self.tree_target()
        if target is None:self.notice('Seleziona scena, shot o sotto-shot da copiare.');return
        self.commit_notes()
        self.copied_node=core.node_snapshot(self.catalog,*target)
        self.notice('Contenuto copiato negli appunti interni. Seleziona una destinazione e premi Ctrl+V.')

    def paste_selected(self):
        target=self.tree_target()
        if target is None or self.copied_node is None:
            self.notice('Copia prima una scena, uno shot o un sotto-shot e seleziona la destinazione.');return
        self.commit_notes()
        self.snapshot()
        try:
            result=core.paste_snapshot(self.catalog,self.copied_node,*target)
            self.last_take_number=None
            self.refresh_scene_tree()
            self.changed()
            self.schedule_sync()
            self.notice(result+' Nessun file originale è stato duplicato.')
        except (core.CatalogError,KeyError,TypeError) as exc:
            self.undo_stack.pop()
            messagebox.showerror('Impossibile incollare',str(exc),parent=self.root)

    def copy_shortcut(self,event):
        if event.widget is self.scene_tree:
            self.copy_selected();return 'break'

    def paste_shortcut(self,event):
        if event.widget is self.scene_tree:
            self.paste_selected();return 'break'

    def show_scene_context(self,event):
        row=self.scene_tree.identify_row(event.y)
        if row:
            self.scene_tree.selection_set(row)
            self.scene_tree.focus(row)
            self.on_scene_select()
        try:self.scene_context.tk_popup(event.x_root,event.y_root)
        finally:self.scene_context.grab_release()

    def active_shot(self,quiet=False):
        n,h=self.selected_ids()
        if n is None or h is None:
            if not quiet:messagebox.showinfo('Seleziona uno shot','Seleziona uno shot a sinistra (es. Scena 1 / Shot 1) prima di associare i file.',parent=self.root)
            return None
        return n,h

    @staticmethod
    def _sync_label(status):
        return {'OK':'✓ OK','KO':'✕ KO','REVIEW':'◐ REVIEW',
                'PENDING':'… WAIT','SINGLE':'— SINGLE','EMPTY':'—'}.get(status,'… WAIT')

    @staticmethod
    def _all_takes(shot):
        return [t for container in [shot]+shot.get('subshots',[])
                for t in container.get('takes',[])]

    def refresh_scene_tree(self,select=None):
        if select is None:
            ss=self.scene_tree.selection();select=ss[0] if ss else self.last_tree_selection
        self._updating=True
        self.scene_tree.delete(*self.scene_tree.get_children())
        for scene in self.catalog['scenes']:
            visible=[]
            for sh in scene['shots']:
                if self.only_unsynced_var.get():
                    direct=scene_sync.node_status(sh['takes']) not in ('EMPTY','OK')
                    subs=[sub for sub in sh.get('subshots',[])
                          if scene_sync.node_status(sub['takes']) not in ('EMPTY','OK')]
                    if not direct and not subs:continue
                else:
                    subs=sh.get('subshots',[])
                    if self.only_empty_var.get():
                        subs=[u for u in subs if core.empty_subshot(u)]
                        if not core.empty_shot(sh) and not subs:continue
                visible.append((sh,subs))
            if (self.only_empty_var.get() or self.only_unsynced_var.get()) and not visible:
                if scene['shots'] or self.only_unsynced_var.get():continue
            all_takes=[t for sh in scene['shots'] for t in self._all_takes(sh)]
            videos=sum(bool(t.get('video')) for t in all_takes)
            audios=sum(bool(t.get('audio')) for t in all_takes)
            status=scene_sync.node_status(all_takes)
            sid=f"s:{scene['number']}"
            empty=core.empty_scene(scene)
            sym='○' if empty and self.highlight_empty_var.get() else '▣'
            tags=('empty_scene',) if empty and self.highlight_empty_var.get() else ('sync_bad',) if status in ('KO','REVIEW') else ('scene',)
            self.scene_tree.insert('','end',iid=sid,
                text=self.tr(f"{sym}  {core.label(self.catalog,scene['number'])}    ({len(scene['shots'])} shot · {videos}V / {audios}A)"),
                values=(self._sync_label(status),),tags=tags,open=True)
            for sh,subs in visible:
                all_shot=self._all_takes(sh)
                v=sum(bool(t.get('video')) for t in all_shot)
                a=sum(bool(t.get('audio')) for t in all_shot)
                status=scene_sync.node_status(all_shot)
                tid=f"t:{scene['number']}:{sh['number']}"
                empty_sh=core.empty_shot(sh)
                prefix='○  ' if empty_sh and self.highlight_empty_var.get() else '    '
                tag=('empty_shot',) if empty_sh and self.highlight_empty_var.get() else ('sync_bad',) if status in ('KO','REVIEW') else ('shot',)
                padding=self.catalog['settings']['padding']
                self.scene_tree.insert(sid,'end',iid=tid,
                    text=self.tr(f"{prefix}{self.catalog['settings']['shot_label']} {str(sh['number']).zfill(padding)}    {v} video / {a} audio"),
                    values=(self._sync_label(status),),tags=tag,open=True)
                for sub in subs:
                    status=scene_sync.node_status(sub['takes'])
                    sub_empty=core.empty_subshot(sub)
                    vid=sum(bool(t.get('video')) for t in sub['takes'])
                    aud=sum(bool(t.get('audio')) for t in sub['takes'])
                    uid=f"u:{scene['number']}:{sh['number']}:{sub['id']}"
                    prefix='○  ' if sub_empty and self.highlight_empty_var.get() else '◦  '
                    tag=('empty_subshot',) if sub_empty and self.highlight_empty_var.get() else ('sync_bad',) if status in ('KO','REVIEW') else ('subshot',)
                    self.scene_tree.insert(tid,'end',iid=uid,
                        text=f"{prefix}{sub['name']}    {vid}V / {aud}A",
                        values=(self._sync_label(status),),tags=tag)
        if select and self.scene_tree.exists(select):
            self.scene_tree.selection_set(select);self.scene_tree.see(select)
        n_scene=sum(core.empty_scene(s) for s in self.catalog['scenes'])
        n_shot=sum(core.empty_shot(sh) for s in self.catalog['scenes'] for sh in s['shots'])
        n_sub=sum(core.empty_subshot(u) for s in self.catalog['scenes'] for sh in s['shots'] for u in sh.get('subshots',[]))
        unsynced=sum(scene_sync.effective_status(t) != 'OK'
                     for s in self.catalog['scenes'] for sh in s['shots'] for t in self._all_takes(sh))
        self.scene_count_var.set(self.tr(f'{n_scene} scene · {n_shot} shot · {n_sub} sotto-shot senza file · ○ = vuoto')+f'  |  {unsynced} sync pending/review/KO')
        self._updating=False
        self.on_scene_select()

    def on_scene_select(self,event=None):
        if self._updating:return
        selected=self.scene_tree.selection()
        new_target=self.tree_target()
        if new_target!=self._editing_node_target:
            self.commit_notes()
        previous=self.last_tree_selection
        if selected:self.last_tree_selection=selected[0]
        if previous != self.last_tree_selection:self.last_take_number=None
        self.queue_save_session()
        n,h=self.selected_ids()
        u=self.selected_subshot_id()
        scene=core.scene_for(self.catalog,n) if n is not None else None
        shot=core.shot_for(self.catalog,n,h) if h is not None else None
        sub=core.subshot_for(self.catalog,n,h,u) if u else None
        self._updating=True
        self.notes_scene_var.set(scene.get('description','') if scene else '')
        self.notes_shot_var.set(shot.get('description','') if shot else '')
        self.notes_subshot_var.set(sub.get('description','') if sub else '')
        self._editing_node_target=new_target
        self.subshot_note.configure(state='normal' if sub else 'disabled')
        self._updating=False
        self.render_takes(sub if sub else shot,n,h)

    def render_takes(self,shot=None,n=None,h=None,select_take=None):
        if n is None or h is None:
            n,h=self.selected_ids()
        u=self.selected_subshot_id()
        if shot is None and n is not None and h is not None:
            shot=core.container_for(self.catalog,n,h,u)
        if select_take is None:select_take=self.last_take_number
        self._updating=True
        self.media_tree.delete(*self.media_tree.get_children())
        self.side_var.set(self.tr('Lato attivo: ')+self.active_side.upper())
        self.media_tree.heading('take',text=self.tr('Ciak'))
        self.media_tree.heading('sync',text='SYNC')
        self.media_tree.heading('video',text=('▶ VIDEO' if self.active_side==VIDEO else 'VIDEO'))
        self.media_tree.heading('audio',text=('▶ AUDIO' if self.active_side==AUDIO else 'AUDIO'))
        if shot is None:
            self.detail_label.config(text=self.tr('CIAK E ABBINAMENTI / SELEZIONA UNO SHOT'))
        else:
            sub=core.subshot_for(self.catalog,n,h,u) if u else None
            self.detail_label.config(text=self.tr(core.label(self.catalog,n,h,sub['name'] if sub else None).upper()+' / CIAK'))
            for t in sorted(shot['takes'],key=lambda x:x['number']):
                v,a=t['video'],t['audio']
                def fmt(m,side):
                    if not m:return '—'
                    mark='▶ ' if self.active_side==side and select_take==t['number'] else '  '
                    return mark+('! ' if not Path(m['path']).is_file() else '')+Path(m['path']).name
                tag=('missing' if any(m and not Path(m['path']).is_file() for m in (v,a)) else
                     'sync_bad' if v and a and scene_sync.effective_status(t) in ('KO','REVIEW') else
                     'paired' if v and a else 'unpaired')
                self.media_tree.insert('','end',iid=str(t['number']),
                         values=(str(t['number'])+(' *' if t.get('manual_number') else ''),
                                 fmt(v,VIDEO),v['quality'] if v else '—',fmt(a,AUDIO),a['quality'] if a else '—',
                                 self._sync_label(scene_sync.effective_status(t))),
                         tags=(tag,))
            if select_take is not None and self.media_tree.exists(str(select_take)):
                self.media_tree.selection_set(str(select_take));self.media_tree.focus(str(select_take));self.media_tree.see(str(select_take))
            self.notice(f'{core.label(self.catalog,n,h,sub["name"] if sub else None)}: {len(shot["takes"])} ciak · trascina i file su una riga per abbinarli.')
        selected_num = self.selected_take()
        selected_item = (core.take_for(self.catalog,n,h,selected_num,u)
                         if n is not None and h is not None and selected_num is not None else None)
        self.take_description_var.set(selected_item.get('description','') if selected_item else '')
        self.take_annotation_var.set(selected_item.get('annotation','') if selected_item else '')
        self.take_description.configure(state='normal' if selected_item else 'disabled')
        self.take_annotation.configure(state='normal' if selected_item else 'disabled')
        self._editing_take_target=(n,h,u,selected_num) if selected_item else None
        self._updating=False

    def selected_take(self):
        selected=self.media_tree.selection()
        return int(selected[0]) if selected else None

    def on_take_select(self,event=None):
        if self._updating:return
        new_number=self.selected_take()
        if new_number is None or new_number==self.last_take_number:return
        self.commit_notes()
        self.last_take_number=new_number
        self.render_takes(select_take=new_number)
        self.queue_save_session()

    def media_click(self,event):
        col=self.media_tree.identify_column(event.x)
        if col in ('#2','#3'):side=VIDEO
        elif col in ('#4','#5'):side=AUDIO
        elif col=='#1':side=None
        else:return
        if side and side!=self.active_side:
            self.active_side=side
            self.root.after_idle(lambda:self.render_takes(select_take=self.selected_take()))
            self.queue_save_session()

    def switch_side(self,side):
        self.active_side=side
        self.render_takes(select_take=self.selected_take())
        self.media_tree.focus_set()
        self.queue_save_session()
        return 'break'

    def new_take(self):
        target=self.active_shot(quiet=True)
        if target is None:self.notice('Seleziona prima uno shot.');return
        root=self.video_browser.path if self.active_side==VIDEO else self.audio_browser.path
        suffixes=core.VIDEO_EXT if self.active_side==VIDEO else core.AUDIO_EXT
        filespec=' '.join('*'+ext for ext in sorted(suffixes))
        path=filedialog.askopenfilename(parent=self.root,title='File per il nuovo ciak ('+self.active_side+')',
                initialdir=str(root),filetypes=[('Media '+self.active_side,filespec),('Tutti i file','*.*')])
        if path:self.attach_files(self.active_side,[path],(*target,self.selected_subshot_id(),None))

    def reset_take_number(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        self.snapshot()
        new=core.reset_take_auto(self.catalog,*target,num,subshot_id=self.selected_subshot_id())
        self.last_take_number=new
        self.refresh_scene_tree(self.last_tree_selection);self.changed()
        self.notice('Numero ciak ripristinato alla sequenza automatica di inserimento.')

    def edit_take_number(self):
        target=self.active_shot(quiet=True);old=self.selected_take()
        if not target or old is None:self.notice('Seleziona un ciak da rinumerare.');return
        val=simpledialog.askinteger('Numero ciak',f'Numero per il ciak {old}:',initialvalue=old,minvalue=1,parent=self.root)
        if val is None:return
        try:
            self.snapshot()
            new=core.set_take_number(self.catalog,*target,old,val,subshot_id=self.selected_subshot_id())
            self.last_take_number=new
            self.refresh_scene_tree(self.last_tree_selection);self.changed()
        except core.CatalogError as exc:
            self.undo_stack.pop();messagebox.showerror('Numero non valido',str(exc),parent=self.root)

    def delete_take(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        if not messagebox.askyesno('Elimina ciak',f'Eliminare il ciak {num} e le sue associazioni?\nI file originali non saranno toccati.',parent=self.root):return
        self.snapshot();core.remove_take(self.catalog,*target,num,subshot_id=self.selected_subshot_id())
        self.last_take_number=None
        self.refresh_scene_tree(self.last_tree_selection);self.changed()

    def add_scene(self):
        self.commit_notes();self.snapshot()
        n=core.add_scene(self.catalog)
        core.add_shot(self.catalog,n,1)
        self.refresh_scene_tree(f't:{n}:1');self.changed()
        self.notice(f'Creata {core.label(self.catalog,n,1)}. Puoi trascinare i file sullo shot.')

    def add_shot(self):
        self.commit_notes()
        n,_=self.selected_ids()
        if n is None:messagebox.showinfo('Scena richiesta','Seleziona prima una scena o un suo shot.',parent=self.root);return
        self.snapshot()
        h=core.add_shot(self.catalog,n)
        self.refresh_scene_tree(f't:{n}:{h}');self.changed()

    def add_subshot(self):
        target=self.active_shot(quiet=True)
        if target is None:
            self.notice('Seleziona prima lo shot che conterrà il sotto-shot.');return
        sh=core.shot_for(self.catalog,*target)
        used={u['name'].casefold() for u in sh.get('subshots',[])}
        suggestion=next((chr(i) for i in range(65,91) if chr(i).casefold() not in used),f'Inquadratura {len(used)+1}')
        name=simpledialog.askstring('Nuovo sotto-shot','Nome libero (es. A, B, Dettaglio, Campo largo):',
                                    initialvalue=suggestion,parent=self.root)
        if name is None:return
        try:
            self.commit_notes()
            name=core.clean_subshot_name(name)
            self.snapshot(); uid=core.add_subshot(self.catalog,*target,name)
            self.refresh_scene_tree(f'u:{target[0]}:{target[1]}:{uid}')
            self.changed()
        except core.CatalogError as exc:
            if self.undo_stack:self.undo_stack.pop()
            messagebox.showerror('Nome non valido',str(exc),parent=self.root)

    def delete_selected(self):
        n,h=self.selected_ids()
        if n is None:return
        name=core.label(self.catalog,n,h)
        u=self.selected_subshot_id()
        if u:name=core.label(self.catalog,n,h,core.subshot_for(self.catalog,n,h,u)['name'])
        msg=f'Eliminare {name} e le sue associazioni?\nI file originali NON verranno cancellati.' 
        if not messagebox.askyesno('Conferma eliminazione',msg,parent=self.root):return
        self.snapshot()
        if h is None:core.remove_scene(self.catalog,n);sel=None
        elif u:core.remove_subshot(self.catalog,n,h,u);sel=f't:{n}:{h}'
        else:core.remove_shot(self.catalog,n,h);sel=f's:{n}'
        self.refresh_scene_tree(sel);self.changed()

    def renumber(self):
        n,h=self.selected_ids()
        if n is None:return
        u=self.selected_subshot_id()
        if u:
            old=core.subshot_for(self.catalog,n,h,u)['name']
            new=simpledialog.askstring('Rinomina sotto-shot',f'Nuovo nome per {old}:',initialvalue=old,parent=self.root)
            if new is None or new==old:return
            try:
                self.snapshot();core.rename_subshot(self.catalog,n,h,u,new)
                self.refresh_scene_tree(f'u:{n}:{h}:{u}');self.changed()
            except core.CatalogError as exc:
                self.undo_stack.pop();messagebox.showerror('Nome non valido',str(exc),parent=self.root)
            return
        target='scena' if h is None else 'shot'
        old=n if h is None else h
        new=simpledialog.askinteger('Rinumera '+target,f'Nuovo numero per {core.label(self.catalog,n,h)}:',initialvalue=old,minvalue=1,parent=self.root)
        if new is None or new==old:return
        try:
            if h is None:
                if core.scene_for(self.catalog,new):raise core.CatalogError('Scena già presente.')
                self.snapshot();core.rename_scene(self.catalog,n,new);select=f's:{new}'
            else:
                if core.shot_for(self.catalog,n,new):raise core.CatalogError('Shot già presente.')
                self.snapshot();core.rename_shot(self.catalog,n,h,new);select=f't:{n}:{new}'
            self.refresh_scene_tree(select);self.changed()
        except core.CatalogError as exc:messagebox.showerror('Numero non valido',str(exc),parent=self.root)

    def commit_notes(self):
        """Persist optional descriptions/annotations for the *form's* prior target.

        Retaining the previous target prevents a click on a different tree item
        from accidentally writing the old text into the newly selected item.
        """
        if self._updating:return
        updates=[]
        target=self._editing_node_target
        if target:
            n,h,u=target
            scene=core.scene_for(self.catalog,n)
            shot=core.shot_for(self.catalog,n,h) if h is not None else None
            sub=core.subshot_for(self.catalog,n,h,u) if u else None
            for obj,value in ((scene,self.notes_scene_var.get()),
                              (shot,self.notes_shot_var.get()),
                              (sub,self.notes_subshot_var.get())):
                if obj is not None and obj.get('description','')!=value:
                    updates.append((obj,'description',value))
        take_key=self._editing_take_target
        if take_key:
            n,h,u,num=take_key
            take=core.take_for(self.catalog,n,h,num,u)
            if take:
                for key,value in (('description',self.take_description_var.get()),
                                  ('annotation',self.take_annotation_var.get())):
                    if take.get(key,'')!=value:
                        updates.append((take,key,value))
        if updates:
            self.snapshot()
            for obj,key,value in updates:obj[key]=value
            self.changed()

    def attach_files(self,kind,paths,target=None):
        if target is None:
            target_ids=self.active_target()
            if target_ids is None:return
            n,h,sub=target_ids
            selected_number=self.selected_take()
        elif len(target)==3:  # historical call sites/tests: (scene,shot,take)
            n,h,selected_number=target;sub=None
        else:
            n,h,sub,selected_number=target
        if not paths:return
        good=[p for p in paths if Path(p).is_file()]
        if not good:return
        self.commit_notes();self.snapshot()
        count=0;errors=[];first_attached=None
        for path in good:
            preferred=core.take_for(self.catalog,n,h,selected_number,sub) if selected_number is not None else None
            to_take=preferred['number'] if preferred and preferred[kind] is None else None
            try:
                take,added=core.add_media(self.catalog,n,h,path,kind,'B',to_take,subshot_id=sub)
                if added:
                    count+=1
                    if first_attached is None:first_attached=take
            except core.CatalogError as exc:errors.append(str(exc))
            selected_number=None
        if count:
            self.schedule_sync()
            self.last_take_number=first_attached['number'] if first_attached else None
            selection=f'u:{n}:{h}:{sub}' if sub else f't:{n}:{h}'
            self.refresh_scene_tree(selection);self.changed()
        elif self.undo_stack:self.undo_stack.pop()
        self.notice(f'{count} file {kind} aggiunti. I media originali non sono modificati.')
        if errors:messagebox.showwarning('Alcuni file non associati','\n'.join(errors[:10]),parent=self.root)

    def set_quality(self,quality):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:
            self.notice('Seleziona una riga ciak e usa ←/→ per scegliere il lato prima di B/R/S.')
            return 'break'
        take=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        media=take[self.active_side] if take else None
        if not media:
            self.notice(f'Ciak {num}: il lato {self.active_side} non contiene alcun file.')
            return 'break'
        if media['quality']==quality:return 'break'
        self.snapshot();media['quality']=quality
        self.refresh_scene_tree(self.last_tree_selection);self.changed()
        self.notice(f'Ciak {num} · {self.active_side}: {quality} = {core.QUALITIES[quality]}.')
        return 'break'

    def remove_media(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        take=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        if take[self.active_side] is None:
            self.notice('Nessun file su questo lato.');return
        self.snapshot()
        core.remove_media(self.catalog,*target,num,self.active_side,self.selected_subshot_id())
        self.last_take_number=num if core.take_for(self.catalog,*target,num,self.selected_subshot_id()) else None
        self.refresh_scene_tree(self.last_tree_selection);self.changed()
        self.notice('Collegamento eliminato; nessun file originale modificato.')

    def open_media(self,event=None):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        if event:
            column=self.media_tree.identify_column(event.x)
            if column=='#1':self.edit_take_number();return
            if column in ('#2','#3'):self.active_side=VIDEO
            elif column in ('#4','#5'):self.active_side=AUDIO
        take=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        media=take[self.active_side] if take else None
        self.render_takes(select_take=num)
        if not media:return
        p=media['path']
        if not Path(p).is_file():messagebox.showerror('File non trovato',p,parent=self.root);return
        try:
            if sys.platform=='win32':os.startfile(p)
            elif sys.platform=='darwin':subprocess.Popen(['open',p])
            else:subprocess.Popen(['xdg-open',p])
        except (OSError,AttributeError) as exc:messagebox.showwarning('Impossibile aprire',str(exc),parent=self.root)

    def update_media_actions(self,event=None):pass

    def start_drag(self,kind,files,x,y):
        if self.dragging:return
        self.dragging={'kind':kind,'files':files}
        ghost=tk.Toplevel(self.root)
        ghost.overrideredirect(True)
        try:ghost.attributes('-topmost',True)
        except tk.TclError:pass
        text=f' {len(files)} {"video" if kind==VIDEO else "audio"} → shot '
        tk.Label(ghost,text=text,bg='#2867aa',fg='white',font=('Segoe UI',10,'bold'),padx=14,pady=9,relief='solid',bd=1).pack()
        self.drag_popup=ghost
        self.drag_motion(x,y)

    def drag_motion(self,x,y):
        if not self.dragging:return
        if self.drag_popup:self.drag_popup.geometry(f'+{x+18}+{y+16}')
        self.root.configure(cursor='hand2')

    def drop_scene_release(self,event):
        # Tk normally delivers the release to the browser that initiated the drag.
        if self.dragging:self.finish_drag(event.x_root,event.y_root)

    def finish_drag(self,x,y):
        if not self.dragging:return
        drag=self.dragging
        # Remove ghost *before* hit testing: otherwise the drop target could be the ghost.
        self.dragging=None
        if self.drag_popup:
            self.drag_popup.destroy();self.drag_popup=None
        self.root.configure(cursor='')
        widget=self.root.winfo_containing(x,y)
        target=None
        if widget is self.scene_tree:
            ty=y-self.scene_tree.winfo_rooty()
            row=self.scene_tree.identify_row(ty)
            if row.startswith('t:'):
                _,n,h=row.split(':');target=(int(n),int(h),None,None)
            elif row.startswith('u:'):
                _,n,h,u=row.split(':',3);target=(int(n),int(h),u,None)
        elif widget is self.media_tree or self._descendant_of(widget,self.media_tree):
            shot_ids=self.active_shot(quiet=True)
            if shot_ids:
                row=self.media_tree.identify_row(y-self.media_tree.winfo_rooty())
                target=(*shot_ids,self.selected_subshot_id(),int(row) if row.isdigit() else None)
        if target:
            self.attach_files(drag['kind'],drag['files'],target)
        else:self.notice('Rilascia i file su uno shot o direttamente sulla riga di ciak da completare.')

    @staticmethod
    def _descendant_of(widget,ancestor):
        while widget is not None:
            if widget is ancestor:return True
            widget=widget.master
        return False

    def localize_dialog(self,win):
        def visit(widget):
            try:widget.configure(text=self.tr(widget.cget('text')))
            except (tk.TclError,AttributeError):pass
            for child in widget.winfo_children():visit(child)
        visit(win)
        win.title(self.tr(win.title()))

    def settings(self):
        win=tk.Toplevel(self.root);win.title('Convenzione nomi');win.configure(bg=self.panel);win.resizable(False,False)
        win.transient(self.root);win.grab_set()
        st=self.catalog['settings']
        vals={key:tk.StringVar(value=str(st[key])) for key in ('scene_label','shot_label','separator','padding')}
        body=ttk.Frame(win,style='Panel.TFrame',padding=20);body.pack(fill='both',expand=True)
        fields=[('Etichetta scena','scene_label'),('Etichetta shot','shot_label'),('Separatore','separator'),('Cifre minime (0–6)','padding')]
        for i,(desc,key) in enumerate(fields):
            ttk.Label(body,text=desc,style='Panel.TLabel').grid(row=i,column=0,sticky='w',pady=8)
            ttk.Entry(body,textvariable=vals[key],width=24).grid(row=i,column=1,sticky='ew',padx=(20,0),pady=8)
        def apply():
            try:pad=int(vals['padding'].get())
            except ValueError:pad=-1
            if not 0<=pad<=6:messagebox.showerror('Valore non valido','Cifre minime: da 0 a 6.',parent=win);return
            if not vals['scene_label'].get().strip() or not vals['shot_label'].get().strip():
                messagebox.showerror('Valore non valido','Le etichette non possono essere vuote.',parent=win);return
            self.snapshot()
            for key in ('scene_label','shot_label','separator'):st[key]=vals[key].get()
            st['padding']=pad
            self.refresh_scene_tree();self.changed();win.destroy()
        buttons=ttk.Frame(body,style='Panel.TFrame');buttons.grid(row=4,column=0,columnspan=2,sticky='e',pady=(12,0))
        ttk.Button(buttons,text='Annulla',command=win.destroy).pack(side='left',padx=5)
        ttk.Button(buttons,text='Applica',style='Primary.TButton',command=apply).pack(side='left')
        self.localize_dialog(win)
        center_window(win,self.root,460,325)

    def new_project(self):
        if not self.ask_save_unsaved():return
        self._remove_draft()
        self.catalog=core.new_catalog();self.filepath=None;self.undo_stack=[];self.changed_unsaved=False
        self.last_tree_selection=None;self.last_take_number=None;self.copied_node=None
        self._editing_node_target=None;self._editing_take_target=None
        self.video_browser.navigate(Path.home(),update_catalog=False)
        self.audio_browser.navigate(Path.home(),update_catalog=False)
        self.refresh_scene_tree();self.update_title();self.notice('Nuovo catalogo creato.')
        self.queue_save_session()

    def ask_save_unsaved(self,on_close=False):
        self.commit_notes()
        if not self.changed_unsaved:return True
        if on_close and not self.filepath:
            question=('Vuoi salvare la bozza con un nome?\n\n'
                      'Sì: scegli un file catalogo.\n'
                      'No: la bozza autosalvata sarà recuperata al prossimo avvio.\n'
                      'Annulla: resta nel programma.')
        else:
            question=('Vuoi salvare il catalogo prima di continuare?\n'
                      'Se scegli No e apri/crei un altro catalogo, abbandoni la bozza corrente.')
        ans=messagebox.askyesnocancel('Catalogo non salvato',question,parent=self.root)
        if ans is None:return False
        if ans:return self.save()
        return True

    def open_project(self):
        if not self.ask_save_unsaved():return
        p=filedialog.askopenfilename(parent=self.root,title='Apri catalogo',filetypes=[('Catalogo SceneSlate','*.json'),('Tutti i file','*.*')])
        if not p:return
        try:c=core.load_catalog(p)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            messagebox.showerror('Apertura non riuscita',str(exc),parent=self.root);return
        self._remove_draft()
        self.catalog=c;self.filepath=p;self.undo_stack=[];self.changed_unsaved=False
        self.last_tree_selection=None;self.last_take_number=None;self.copied_node=None
        self._editing_node_target=None;self._editing_take_target=None
        for kind,browser in ((VIDEO,self.video_browser),(AUDIO,self.audio_browser)):
            folder=c.get(f'{kind}_root')
            if folder and Path(folder).is_dir():browser.navigate(folder,update_catalog=False)
        self.refresh_scene_tree();self.update_title();self.notice(f'Catalogo aperto: {Path(p).name}')
        self.queue_save_session()

    def save(self):
        self.commit_notes()
        if not self.filepath:return self.save_as()
        try:core.save_catalog(self.catalog,self.filepath)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Salvataggio non riuscito',str(exc),parent=self.root);return False
        self.changed_unsaved=False;self.update_title();self.notice('Catalogo salvato.');return True

    def save_as(self):
        self.commit_notes()
        p=filedialog.asksaveasfilename(parent=self.root,title='Salva catalogo',defaultextension='.json',initialfile='my_catalog.sceneslate.json',filetypes=[('Catalogo JSON','*.json')])
        if not p:return False
        self.filepath=p
        result=self.save()
        if result:
            self._remove_draft()
            self.queue_save_session()
        return result

    def schedule_sync(self, retry=False, selected=None):
        """Only enqueue immutable paths; all catalog/Tk mutations remain on UI thread."""
        if not all(scene_sync.executables()):return
        for scene,shot,sub,container in core.iter_containers(self.catalog):
            for t in container['takes']:
                if not t.get('video') or not t.get('audio'):continue
                if selected is not None and t is not selected:continue
                status=scene_sync.effective_status(t)
                if retry or status=='PENDING':
                    if retry:t['sync']=None
                    self._sync_worker.submit(t['video']['path'],t['audio']['path'])

    def poll_sync(self):
        changed=False
        for key,result in self._sync_worker.receive():
            for _scene,_shot,_sub,container in core.iter_containers(self.catalog):
                for take in container['takes']:
                    v,a=take.get('video'),take.get('audio')
                    if not (v and a):continue
                    if self._sync_worker.key(v['path'],a['path']) != key:continue
                    if result['signature'] != scene_sync.fingerprint(v['path'],a['path']):continue
                    current=take.get('sync') or {}
                    if current.get('method')=='manual' and scene_sync.effective_status(take)=='OK':continue
                    take['sync']=copy.deepcopy(result)
                    changed=True
        if changed:
            self.changed()
            self.refresh_scene_tree()
        if not self._sync_worker.closed:
            self._sync_timer=self.root.after(400,self.poll_sync)

    def retry_sync(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if target is None or num is None:
            self.notice('Select a take to retry waveform sync.');return
        t=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        if not t or not t.get('video') or not t.get('audio'):
            self.notice('This take needs both video and audio.');return
        if scene_sync.effective_status(t)=='OK' and (t.get('sync') or {}).get('method')=='manual':
            if not messagebox.askyesno('Replace manual alignment?',
                'Automatic synchronization will replace the manually verified offset. Continue?',parent=self.root):
                return
        t['sync']=None
        self.schedule_sync(retry=True,selected=t)
        self.refresh_scene_tree()
        self.changed()
        self.notice('Waveform synchronization queued.')

    def edit_sync(self):
        """Open the precision editor for a paired take."""
        target=self.active_shot(quiet=True)
        number=self.selected_take()
        if target is None or number is None:
            self.notice('Select a take to edit synchronization.');return
        sub_id=self.selected_subshot_id()
        take=core.take_for(self.catalog,*target,number,sub_id)
        if not take or not take.get('video') or not take.get('audio'):
            self.notice('This take needs both video and audio.');return
        video=take['video']['path'];audio=take['audio']['path']
        signature=scene_sync.fingerprint(video,audio)
        if not all(scene_sync.executables()):
            self.ffmpeg_setup(manual=True)
            return

        def approve(offset):
            if not (take.get('video') and take.get('audio')) or \
                scene_sync.fingerprint(take['video']['path'],take['audio']['path'])!=signature:
                raise RuntimeError('Paired media changed while editing; reopen the sync editor.')
            self.snapshot()
            record=scene_sync.sync_record('OK',offset_seconds=offset,score=None,
                    method='manual',signature=signature,
                    error='Manually approved after listening; check long-take drift.')
            record['manual_verified']=True
            take['sync']=record
            self.changed()
            self.refresh_scene_tree()
            self.notice('Manual synchronization saved. XML export will use the verified offset.')

        SyncEditor(self.root,video,audio,take.get('sync'),approve,language=self.language)

    def sync_details(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if target is None or num is None:return
        t=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        status=scene_sync.effective_status(t)
        record=t.get('sync') or {}
        message=(f'{self.tr("Status:")} {status}\n{self.tr("Offset (audio source at video zero):")} '
            f'{record.get("offset_seconds")} s\nCorrelation score: {record.get("score")}\n'
            f'{self.tr("Method:")} {record.get("method", "waveform")}\n'
            f'{self.tr("Note:")} {record.get("error", "") or "None"}\n\n'
            'OK matches are still worth checking by listening.')
        messagebox.showinfo(self.tr('Waveform sync details'),message,parent=self.root)

    def export(self):
        self.commit_notes()
        # Four independent export formats, enabled by default.
        dialog=tk.Toplevel(self.root)
        dialog.title(self.tr('Export options'));dialog.configure(bg=self.panel)
        dialog.transient(self.root);dialog.grab_set()
        pane=ttk.Frame(dialog,style='Panel.TFrame',padding=18);pane.pack(fill='both',expand=True)
        modes=[('csv','CSV metadata and reports'),('take','Individual take XML timelines'),
               ('shot','Shot XML review timelines'),('scene','Scene XML review timelines')]
        vars={key:tk.BooleanVar(value=True) for key,_ in modes}
        ttk.Label(pane,text=self.tr('Choose exports:'),style='Section.TLabel').pack(anchor='w',pady=(0,8))
        for key,title in modes:
            ttk.Checkbutton(pane,text=self.tr(title),variable=vars[key]).pack(anchor='w',pady=2)
        ttk.Label(pane,text=self.tr('XML timeline frame rate:'),style='Panel.TLabel').pack(anchor='w',pady=(10,3))
        fps_var=tk.StringVar(value=str(self.catalog['settings'].get('timeline_fps',25)))
        ttk.Combobox(pane,textvariable=fps_var,state='readonly',width=12,
             values=['23.976','24','25','29.97','30','50','59.94','60']).pack(anchor='w')
        selected=[]
        def accept():
            if not any(v.get() for v in vars.values()):
                messagebox.showerror('Export','Select at least one format.',parent=dialog);return
            selected.append(([key for key,v in vars.items() if v.get()],float(fps_var.get())))
            dialog.destroy()
        controls=ttk.Frame(pane,style='Panel.TFrame');controls.pack(fill='x',pady=(16,0))
        ttk.Button(controls,text=self.tr('Cancel'),command=dialog.destroy).pack(side='right',padx=3)
        ttk.Button(controls,text=self.tr('Export…'),command=accept,style='Primary.TButton').pack(side='right',padx=3)
        center_window(dialog,self.root,440,345)
        self.root.wait_window(dialog)
        if not selected:return
        modes,fps=selected[0]
        dest=filedialog.askdirectory(parent=self.root,title='Choose export directory')
        if not dest:return
        try:
            count,warnings=core.export_all(self.catalog,dest,modes=modes,fps=fps)
        except (OSError,ValueError,core.CatalogError) as exc:
            messagebox.showerror('Export failed',str(exc),parent=self.root);return
        self.notice(f'Export completed: {count} Resolve metadata rows, {len(warnings)} warnings')
        messagebox.showinfo('Export completed',
            f'Exported to: {dest}\nModes: {", ".join(modes)}\n'
            f'Resolve rows: {count}\nWarnings: {len(warnings)}\n'
            'See export_report.txt for skipped/unsynced media.',parent=self.root)

    def undo(self):
        if not self.undo_stack:self.notice('Nessuna modifica da annullare.');return
        self.catalog=self.undo_stack.pop()
        self._editing_node_target=None;self._editing_take_target=None
        self.refresh_scene_tree()
        self.changed();self.notice('Ultima modifica annullata.')

    def on_root_destroy(self,event):
        if event.widget is not self.root:return
        self._sync_worker.close()
        if self._sync_timer is not None:
            try:self.root.after_cancel(self._sync_timer)
            except tk.TclError:pass
            self._sync_timer=None

    def close(self):
        if not self.ask_save_unsaved(on_close=True):return
        # Persist complete browsing state even if the last action was only scrolling.
        if self._session_after_id is not None:
            self.root.after_cancel(self._session_after_id)
            self._session_after_id=None
        self.save_session()
        self._sync_worker.close()
        if self._sync_timer is not None:
            try:self.root.after_cancel(self._sync_timer)
            except tk.TclError:pass
        self.root.destroy()


def main():
    import argparse
    parser=argparse.ArgumentParser(description='SceneSlate - video/audio footage logging')
    parser.add_argument('--export',metavar='CATALOG.json',help='Export without GUI')
    parser.add_argument('--out',metavar='DIRECTORY',help='Output directory for --export')
    parser.add_argument('--modes',default='csv,take,shot,scene',help='Comma-separated: csv,take,shot,scene')
    parser.add_argument('--fps',type=float,default=None,help='XML timeline FPS (default from catalog)')
    parser.add_argument('project',nargs='?',help='Catalog to open')
    args=parser.parse_args()
    if args.export:
        if not args.out:parser.error('--export requires --out DIRECTORY')
        c=core.load_catalog(args.export)
        count,warnings=core.export_all(c,args.out,modes=args.modes.split(','),fps=args.fps)
        print(f'Exported {count} files for Resolve; {len(warnings)} warnings.')
        for w in warnings:print('WARNING:',w)
        return
    root=tk.Tk();app=SceneSlateApp(root)
    app.startup(args.project)
    root.after(850,app.maybe_prompt_ffmpeg)
    root.mainloop()


if __name__=='__main__':main()
