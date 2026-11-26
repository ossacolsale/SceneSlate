#!/usr/bin/env python3
"""SceneSlate: lightweight desktop footage logging for Windows and Linux."""
from __future__ import annotations

import copy
import math
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
from scene_sync_editor import SyncEditor, QuickSyncReview

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
        if self.kind==VIDEO:
            self.tree.bind('<F4>',self.preview_video)
            self.tree.bind('<Control-Return>',self.preview_video)
        self.tree.bind('<Button-3>',self.preview_menu)
        self.preview_context=tk.Menu(self.tree,tearoff=False)
        self.assignment_menu=tk.Menu(self.preview_context,tearoff=False)
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

    def preview_menu(self,event):
        row=self.tree.identify_row(event.y)
        if not row or not Path(row).is_file():return
        self.tree.selection_set(row);self.tree.focus(row)
        menu=self.preview_context
        menu.delete(0,'end')
        if self.kind==VIDEO:
            menu.add_command(label=self.app.tr('Play selected video (F4)'),command=lambda:self.after_idle(self.preview_video))
            menu.add_command(label=self.app.tr('Video player…'),command=lambda:self.after_idle(self.app.choose_video_player))
            menu.add_command(label=self.app.tr('Use system video player'),command=self.app.reset_video_player)
            menu.add_separator()
        assignments=self.assignment_menu
        assignments.delete(0,'end')
        groups=core.media_assignments(self.app.catalog,row,self.kind)
        if not groups:
            assignments.add_command(label=self.app.tr('No assignments'),state='disabled')
        for i,group in enumerate(groups,1):
            linked=len(group['items'])>1
            if i>1:assignments.add_separator()
            assignments.add_command(label=(self.app.tr('Linked group')+f' {i}' if linked else self.app.tr('Independent assignment')),state='disabled')
            for item in group['items']:
                prefix=(f'⇄ {i} · ' if linked else '○ · ')
                title=prefix+item['label']+' / '+self.app.tr('Ciak')+' '+str(item['target'][3])
                assignments.add_command(label=title,command=lambda target=item['target'],path=row:self.after_idle(lambda:self.app.go_to_assignment(target,path,self.kind)))
        menu.add_cascade(label=self.app.tr('File assignments')+f' ({sum(len(g["items"]) for g in groups)})',menu=assignments)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def preview_video(self,event=None):
        paths=self.selected_files()
        if paths:self.app.launch_media(paths[0],VIDEO)
        return 'break'

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
        self.video_player = self._session.get('video_player','')
        if not isinstance(self.video_player,str): self.video_player='' 
        self._ffmpeg_prompt_suppressed = bool(self._session.get('ffmpeg_prompt_suppressed',False))
        self._ffmpeg_ask_var = tk.BooleanVar(value=not self._ffmpeg_prompt_suppressed)
        self._ffmpeg_installing = False
        self.language = self._session.get('language') if self._session.get('language') in LANGUAGES else 'en'
        global _ACTIVE_LANGUAGE
        _ACTIVE_LANGUAGE = self.language
        self.language_var = tk.StringVar(value=LANGUAGES[self.language])
        self._ui_labels = {}
        self._menu_labels = {}
        self._link_tooltips = {}
        self._hover_link_id = None
        self._hover_link_after = None
        self._hover_link_window = None
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
        self.sync_filter='any'
        self.take_filter='any'
        self.sync_filter_choice=tk.StringVar(value='All')
        self.take_filter_choice=tk.StringVar(value='All')
        self.details_expanded=False
        self._sync_worker=SyncWorker()
        self._sync_timer=None
        self.only_empty_var=tk.BooleanVar(value=False)
        self.highlight_empty_var=tk.BooleanVar(value=True)
        self._updating=False
        self.logo_image=None
        self.logo_header_image=None
        self.load_branding()
        self.make_styles()
        self.make_ui()
        self.set_details_expanded(False)
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

    def load_branding(self):
        logo_path = Path(__file__).with_name('sceneslate_icon.png')
        ico_path = Path(__file__).with_name('sceneslate_logo.ico')
        if ico_path.is_file():
            try:
                self.root.iconbitmap(default=str(ico_path))
            except tk.TclError:
                pass
        if not logo_path.is_file():
            return
        try:
            self.logo_image = tk.PhotoImage(master=self.root,file=str(logo_path))
            try:
                self.root.iconphoto(True, self.logo_image)
            except tk.TclError:
                pass
            try:
                self.logo_header_image = self.logo_image.subsample(max(1,self.logo_image.width()//36),max(1,self.logo_image.height()//36))
            except tk.TclError:
                self.logo_header_image = self.logo_image
        except tk.TclError:
            self.logo_image = None
            self.logo_header_image = None

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
        brand_frame=ttk.Frame(header,style='Root.TFrame');brand_frame.pack(side='left')
        if self.logo_header_image is not None:
            tk.Label(brand_frame,image=self.logo_header_image,bg=self.bg,bd=0,highlightthickness=0).pack(side='left',padx=(0,10))
        title_frame=ttk.Frame(brand_frame,style='Root.TFrame');title_frame.pack(side='left')
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
        self.tools_menu.add_separator()
        self.tools_menu.add_command(label='Play selected video (F4)',command=lambda:self.root.after_idle(self.play_selected_video))
        self.tools_menu.add_command(label='Video player…',command=lambda:self.root.after_idle(self.choose_video_player))
        self.tools_menu.add_command(label='Use system video player',command=self.reset_video_player)
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
        for text,action,sty in [('+ Scena',self.add_scene,'Primary.TButton'),('+ Shot',self.add_shot,'Primary.TButton'),('+ Sotto-shot',self.add_subshot,'Primary.TButton'),('⇄ Collegamenti…',self.manage_links,'TButton')]:
            ttk.Button(controls,text=text,command=action,style=sty).pack(side='left',padx=(0,5))
        scene_wrap=ttk.Frame(left,style='Panel.TFrame');scene_wrap.pack(fill='both',expand=True)
        self.scene_tree=ttk.Treeview(scene_wrap,columns=('scene','shot','subshot','info','sync'),show='headings',selectmode='browse',height=5)
        for col, name, width in [('scene','Scene',76),('shot','Shot',56),('subshot','Sub-shot',88),('info','Media / links',270)]:
            self.scene_tree.heading(col,text=self.tr(name))
            self.scene_tree.column(col,width=width,minwidth=width if col!='info' else 100,stretch=col=='info',anchor='w')
        self.scene_tree.heading('sync',text='SYNC')
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
        self.scene_tree.bind('<Motion>',self._on_link_hover,add='+')
        self.scene_tree.bind('<Leave>',lambda event:self._hide_link_tooltip(),add='+')
        self.scene_tree.bind('<ButtonPress-1>',lambda event:self._hide_link_tooltip(),add='+')
        self.scene_tree.bind('<MouseWheel>',lambda event:self._hide_link_tooltip(),add='+')
        self.scene_context=tk.Menu(self.root,tearoff=False)
        self.scene_context.add_command(label='Copia contenuto  (Ctrl+C)',command=self.copy_selected)
        self.scene_context.add_command(label='Incolla qui  (Ctrl+V)',command=self.paste_selected)
        self.scene_context.add_separator()
        self.scene_context.add_command(label='Gestisci collegamenti…',command=self.manage_links)
        self.scene_context.add_command(label='Rinomina / Rinumera…',command=self.renumber)
        self.scene_context.add_command(label='Svuota contenuto…',command=lambda:self.root.after_idle(self.clear_selected_content))
        self.scene_context.add_command(label='Elimina…',command=self.delete_selected)
        copy_row=controls
        b=ttk.Button(copy_row,text='⧉',width=3,command=self.copy_selected);b.pack(side='left',padx=(0,3))
        self.tip(b,'Copy the selected node content (Ctrl+C).')
        b=ttk.Button(copy_row,text='↳',width=3,command=self.paste_selected);b.pack(side='left',padx=(0,3))
        self.tip(b,'Paste into the selected node (Ctrl+V).')

        filter_row=ttk.Frame(left,style='Panel.TFrame');filter_row.pack(fill='x',pady=(6,0))
        ttk.Label(filter_row,text='SYNC:',style='Panel.TLabel').pack(side='left',padx=(0,4))
        self.sync_filter_combo=ttk.Combobox(filter_row,textvariable=self.sync_filter_choice,
                   width=13,state='readonly',style='Sort.TCombobox')
        self.sync_filter_combo.pack(side='left',padx=(0,10))
        self.sync_filter_combo.bind('<<ComboboxSelected>>',self._choose_sync_filter)
        ttk.Label(filter_row,text='Takes:',style='Panel.TLabel').pack(side='left',padx=(0,4))
        self.take_filter_combo=ttk.Combobox(filter_row,textvariable=self.take_filter_choice,
                   width=14,state='readonly',style='Sort.TCombobox')
        self.take_filter_combo.pack(side='left',padx=(0,10))
        self.take_filter_combo.bind('<<ComboboxSelected>>',self._choose_take_filter)
        ttk.Checkbutton(filter_row,text='Evidenzia vuoti',variable=self.highlight_empty_var,
                        command=self.scene_filter_changed).pack(side='left')
        self._configure_filter_choices()
        self.scene_count_var=tk.StringVar(value='')
        ttk.Label(left,textvariable=self.scene_count_var,style='Muted.TLabel').pack(anchor='w',pady=(3,0))

        detail_head=ttk.Frame(left,style='Panel.TFrame');detail_head.pack(fill='x',pady=(12,4))
        self.detail_label=ttk.Label(detail_head,text='CIAK E ABBINAMENTI',style='Section.TLabel');self.detail_label.pack(anchor='w')
        take_tools=ttk.Frame(detail_head,style='Panel.TFrame');take_tools.pack(fill='x',pady=(4,0))
        for title,action in [('+ Ciak',self.new_take),('Quick review (P)',self.quick_review),('✎ Sync editor',self.edit_sync),('↻ Sync',self.retry_sync)]:
            b=ttk.Button(take_tools,text=title,command=action);b.pack(side='left',padx=(0,4))
            if title=='Quick review (P)':self.tip(b,'Play proposed alignment immediately; confirm or open the editor (P).')
        self.take_tools_button=ttk.Menubutton(take_tools,text='Take actions…')
        self.take_tools_menu=tk.Menu(self.take_tools_button,tearoff=False)
        for title,action in [('Sync details',self.sync_details),('N° ciak…',self.edit_take_number),('↻ Auto',self.reset_take_number),('− Ciak',self.delete_take)]:
            self.take_tools_menu.add_command(label=title,command=lambda fn=action:self.root.after_idle(fn))
        self.take_tools_button.configure(menu=self.take_tools_menu);self.take_tools_button.pack(side='left')
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
        self.media_tree.bind('<KeyPress>',self.rating_shortcut)
        self.media_tree.bind('<Return>',self.play_selected_video)
        self.media_tree.bind('<F4>',self.play_selected_video)
        self.media_tree.bind('<Button-3>',self.show_take_video_menu)
        self.take_video_menu=tk.Menu(self.media_tree,tearoff=False)
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
        self.rating_buttons={}
        for q,name in core.QUALITIES.items():
            btn=ttk.Button(r,text=f'{q} · {name}',command=lambda q=q:self.set_quality(q))
            btn.pack(side='left',padx=2);self.rating_buttons[q]=btn
        self.tip(self.media_tree,'Select video/audio with Left/Right. Select take with Up/Down. Drag files onto a take to pair them.')
        self.details_toggle=ttk.Button(left,text='▸ Descriptions / Notes',command=self.toggle_details)
        self.details_toggle.pack(fill='x',pady=(7,1))
        self.details_content=ttk.Frame(left,style='Panel.TFrame')
        take_notes=ttk.Frame(self.details_content,style='Panel.TFrame');take_notes.pack(fill='x',pady=(4,0))
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
        n=ttk.Frame(self.details_content,style='Panel.TFrame');n.pack(fill='x',pady=(7,0))
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

    def tip(self,widget,message):
        state={'after':None,'window':None}
        def hide(event=None):
            if state['after'] is not None:
                try:widget.after_cancel(state['after'])
                except tk.TclError:pass
                state['after']=None
            if state['window'] is not None:
                try:state['window'].destroy()
                except tk.TclError:pass
                state['window']=None
        def show():
            state['after']=None
            if not widget.winfo_exists():return
            win=tk.Toplevel(widget);state['window']=win;win.overrideredirect(True)
            win.geometry(f'+{widget.winfo_pointerx()+12}+{widget.winfo_pointery()+18}')
            tk.Label(win,text=self.tr(message),bg='#263b50',fg='white',padx=8,pady=5,wraplength=440).pack()
        def enter(event):
            hide();state['after']=widget.after(700,show)
        widget.bind('<Enter>',enter,add='+');widget.bind('<Leave>',hide,add='+')
        widget.bind('<ButtonPress>',hide,add='+');widget.bind('<Destroy>',hide,add='+')

    def tr(self,message):
        return translate(message,self.language)

    @staticmethod
    def _sync_filter_options():
        return [('any','All'),('OK','OK'),('REVIEW','REVIEW'),('KO','KO'),
                ('PENDING','WAIT'),('SINGLE','One-sided (SINGLE)'),('EMPTY','EMPTY'),
                ('attention','Needs review')]

    @staticmethod
    def _take_filter_options():
        return [('any','All'),('has','With takes'),('none','Without takes')]

    def _configure_filter_choices(self):
        for widget,var,options,current in (
            (self.sync_filter_combo,self.sync_filter_choice,self._sync_filter_options(),self.sync_filter),
            (self.take_filter_combo,self.take_filter_choice,self._take_filter_options(),self.take_filter)):
            widget.configure(values=[self.tr(label) for code,label in options])
            var.set(next((self.tr(label) for code,label in options if code==current),self.tr('All')))

    def _choose_sync_filter(self,event=None):
        self.sync_filter=next((code for code,label in self._sync_filter_options()
                    if self.tr(label)==self.sync_filter_choice.get()),'any')
        self.only_unsynced_var.set(False)
        self.only_empty_var.set(False)
        self.scene_filter_changed()

    def _choose_take_filter(self,event=None):
        self.take_filter=next((code for code,label in self._take_filter_options()
                    if self.tr(label)==self.take_filter_choice.get()),'any')
        self.only_empty_var.set(False)
        self.scene_filter_changed()

    def _filter_matches(self,takes):
        status=scene_sync.node_status(takes)
        sync_filter=('attention' if self.only_unsynced_var.get() else self.sync_filter)
        take_filter=('none' if self.only_empty_var.get() else self.take_filter)
        sync_ok = (sync_filter=='any' or status==sync_filter or
                   (sync_filter=='SINGLE' and any(
                       scene_sync.effective_status(t)=='SINGLE' for t in takes)) or
                   (sync_filter=='attention' and status in ('KO','REVIEW','PENDING')))
        take_ok = (take_filter=='any' or
                   (take_filter=='has' and bool(takes)) or
                   (take_filter=='none' and not takes))
        return sync_ok and take_ok

    def _render_details_toggle(self):
        if hasattr(self,'details_toggle'):
            self.details_toggle.configure(text=('▾ ' if self.details_expanded else '▸ ')+
                            self.tr('Descriptions / Notes'))

    def set_details_expanded(self,value):
        new=bool(value)
        self.details_expanded=new
        if new:
            if not self.details_content.winfo_manager():
                self.details_content.pack(fill='x',pady=(0,4))
        elif self.details_content.winfo_manager():
            self.commit_notes()
            self.details_content.pack_forget()
        self._render_details_toggle()
        self.queue_save_session()

    def toggle_details(self):
        self.set_details_expanded(not self.details_expanded)

    def _linked_names(self,n,h=None,u=None):
        """Full labels of every other member, never abbreviate or truncate."""
        try:refs=core.linked_refs(self.catalog,n,h,u)
        except core.CatalogError:return []
        current=core.node_ref(n,h,u)
        names=[]
        for ref in refs:
            if ref==current:continue
            parts=ref.split(':')
            scene_number=int(parts[1])
            shot_number=int(parts[2]) if len(parts)>2 else None
            if parts[0]=='subshot':
                sub=core.subshot_for(self.catalog,scene_number,shot_number,parts[3])
                if not sub:continue
                name=core.label(self.catalog,scene_number,shot_number,sub['name'])
            else:
                name=core.label(self.catalog,scene_number,shot_number)
            names.append(name)
        return sorted(names,key=str.casefold)

    def _linked_suffix(self,n,h=None,u=None):
        names=self._linked_names(n,h,u)
        return '  ⇄ '+', '.join(names) if names else ''

    def _remember_link_tooltip(self,item_id,n,h=None,u=None):
        names=self._linked_names(n,h,u)
        if names:self._link_tooltips[item_id]=self.tr('Linked with:')+'\n'+'\n'.join('• '+name for name in names)

    def _hide_link_tooltip(self):
        after_id=getattr(self,'_hover_link_after',None)
        self._hover_link_after=None
        if after_id is not None:
            try:self.root.after_cancel(after_id)
            except tk.TclError:pass
        popup=getattr(self,'_hover_link_window',None)
        self._hover_link_window=None
        if popup is not None:
            try:popup.destroy()
            except tk.TclError:pass
        self._hover_link_id=None

    def _on_link_hover(self,event):
        row=self.scene_tree.identify_row(event.y)
        if row==self._hover_link_id:return
        self._hide_link_tooltip()
        if not row or row not in self._link_tooltips or self.dragging:return
        self._hover_link_id=row
        self._hover_link_after=self.root.after(500,
            lambda r=row,x=event.x_root,y=event.y_root:self._show_link_tooltip(r,x,y))

    def _show_link_tooltip(self,row,x,y):
        self._hover_link_after=None
        if row!=self._hover_link_id or row not in self._link_tooltips:return
        if not self.scene_tree.exists(row):return
        tip=tk.Toplevel(self.root)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.configure(bg='#425c76')
        try:tip.attributes('-topmost',True)
        except tk.TclError:pass
        text=tk.Label(tip,text=self._link_tooltips[row],justify='left',anchor='w',
                      bg='#142437',fg='#e6f3ff',padx=12,pady=9,
                      wraplength=530,font=('Segoe UI',9))
        text.pack(padx=1,pady=1)
        tip.update_idletasks()
        w=tip.winfo_reqwidth();h=tip.winfo_reqheight()
        px=min(x+16,max(0,tip.winfo_screenwidth()-w-6))
        py=min(y+18,max(0,tip.winfo_screenheight()-h-6))
        tip.geometry(f'+{px}+{py}')
        tip.deiconify()
        self._hover_link_window=tip

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
        self._configure_filter_choices()
        self._render_details_toggle()
        self.media_tree.heading('take',text=self.tr('Ciak'))
        self.refresh_rating_labels()
        self.media_tree.heading('sync',text='SYNC')
        for col,name in [('scene','Scene'),('shot','Shot'),('subshot','Sub-shot'),('info','Media / links')]:
            self.scene_tree.heading(col,text=self.tr(name))
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
        """Ask once per launch, unless suppressed or both tools are available."""
        if self._ffmpeg_prompt_suppressed or self._ffmpeg_installing:return
        if not all(scene_sync.executables()):
            self.ffmpeg_setup(manual=False)

    def ffmpeg_setup(self, manual=False):
        """Show an explicit consent dialog; no download occurs by opening it."""
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
        """Background installation: Tk is touched only from the polling callback."""
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
        """Reprocess only legacy KO entries caused solely by missing tools."""
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
                'sync_filter':self.sync_filter,
                'take_filter':self.take_filter,
                'details_expanded':self.details_expanded,
                'video_player':self.video_player,
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
        self.sync_filter=state.get('sync_filter','any')
        if self.sync_filter not in dict(self._sync_filter_options()):self.sync_filter='any'
        self.take_filter=state.get('take_filter','any')
        if self.take_filter not in dict(self._take_filter_options()):self.take_filter='any'
        self._configure_filter_choices()
        self.set_details_expanded(bool(state.get('details_expanded',False)))
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

    def _target_text(self, n, h=None, u=None):
        if n is None:
            return ''
        if u:
            sub = core.subshot_for(self.catalog, n, h, u)
            return core.label(self.catalog, n, h, sub['name'] if sub else None)
        return core.label(self.catalog, n, h)

    def _propagate_related_links(self, n=None, h=None, u=None):
        if n is None:
            return 0
        count = 0
        scene = core.scene_for(self.catalog, n)
        shot = core.shot_for(self.catalog, n, h) if h is not None else None
        sub = core.subshot_for(self.catalog, n, h, u) if u else None
        if scene and scene.get('link_group'):
            count += core.propagate_links(self.catalog, n)
        if shot and shot.get('link_group'):
            count += core.propagate_links(self.catalog, n, h)
        if sub and sub.get('link_group'):
            count += core.propagate_links(self.catalog, n, h, u)
        return count

    def manage_links(self):
        target = self.tree_target()
        if target is None:
            self.notice('Select a scene, shot or sub-shot first.'); return
        n, h, u = target
        kind = 'scene' if h is None else 'subshot' if u else 'shot'
        current_label = self._target_text(n, h, u)
        current_ref = core.node_ref(n, h, u)
        linked = set(core.linked_refs(self.catalog, n, h, u))
        win = tk.Toplevel(self.root)
        win.title(self.tr('Link selector'))
        win.configure(bg=self.panel)
        win.transient(self.root); win.grab_set()
        outer = ttk.Frame(win, style='Panel.TFrame', padding=18)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text=self.tr('Select linked items'), style='Section.TLabel').pack(anchor='w')
        ttk.Label(outer, text=self.tr('Changes to takes and descriptions will be mirrored across all linked items of the same kind.'), style='Muted.TLabel', wraplength=520, justify='left').pack(anchor='w', fill='x', pady=(4, 10))
        ttk.Label(outer, text=self.tr('Current item:') + ' ' + current_label, style='Panel.TLabel').pack(anchor='w', pady=(0, 8))
        listbox = ttk.Frame(outer, style='Panel.TFrame')
        listbox.pack(fill='both', expand=True)
        canvas = tk.Canvas(listbox, bg=self.deep, highlightthickness=0, height=280)
        scroll = ttk.Scrollbar(listbox, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas, style='Panel.TFrame')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')) )
        canvas.create_window((0,0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        def wheel(event):
            number=getattr(event,'num',None)
            delta=getattr(event,'delta',0)
            units=-1 if number==4 else 1 if number==5 else -int(math.copysign(max(1,abs(delta)//120),delta)) if delta else 0
            if units:canvas.yview_scroll(units,'units')
            return 'break'
        # Toplevel bindings receive wheel events from its descendant widgets too.
        for sequence in ('<MouseWheel>','<Button-4>','<Button-5>'):
            win.bind(sequence,wheel,add='+')
        checks = {}
        buttons=[]
        def focus_item(index):
            if not buttons:return 'break'
            index=max(0,min(len(buttons)-1,index))
            btn=buttons[index];btn.focus_set()
            canvas.update_idletasks()
            total=max(1,body.winfo_reqheight());top=canvas.canvasy(0);y=btn.winfo_y()
            if y<top:canvas.yview_moveto(y/total)
            elif y+btn.winfo_height()>top+canvas.winfo_height():
                canvas.yview_moveto((y+btn.winfo_height()-canvas.winfo_height())/total)
            return 'break'
        for ref, node_kind, _node in core.iter_nodes(self.catalog, kind):
            if ref == current_ref:
                continue
            parts = ref.split(':')
            if kind == 'scene':
                label = self._target_text(int(parts[1]))
            elif kind == 'shot':
                label = self._target_text(int(parts[1]), int(parts[2]))
            else:
                label = self._target_text(int(parts[1]), int(parts[2]), parts[3])
            var = tk.BooleanVar(value=ref in linked)
            checks[ref] = var
            btn=ttk.Checkbutton(body,text=label,variable=var)
            btn.pack(anchor='w',fill='x',padx=8,pady=3)
            i=len(buttons);buttons.append(btn)
            btn.bind('<Up>',lambda e,i=i:focus_item(i-1))
            btn.bind('<Down>',lambda e,i=i:focus_item(i+1))
            btn.bind('<Home>',lambda e:focus_item(0))
            btn.bind('<End>',lambda e:focus_item(len(buttons)-1))
        win.after_idle(lambda:focus_item(0))
        def apply_links():
            chosen = [ref for ref, var in checks.items() if var.get()]
            self.commit_notes()
            self.snapshot()
            try:
                gid = core.configure_links(self.catalog, n, h, u, chosen)
                self.refresh_scene_tree(self.last_tree_selection)
                self.changed()
                if gid:
                    self.notice('Links updated.')
                else:
                    self.notice('Links removed.')
                win.destroy()
            except core.CatalogError as exc:
                if self.undo_stack: self.undo_stack.pop()
                messagebox.showerror(self.tr('Cannot update links'), str(exc), parent=win)
        footer = ttk.Frame(outer, style='Panel.TFrame')
        footer.pack(fill='x', pady=(10, 0))
        ttk.Button(footer, text=self.tr('Cancel'), command=win.destroy).pack(side='right', padx=(5,0))
        ttk.Button(footer, text=self.tr('Apply'), command=apply_links, style='Primary.TButton').pack(side='right')
        center_window(win, self.root, 620, 470)

    def go_to_assignment(self,target,path,kind):
        n,h,u,num=target
        self.commit_notes()
        take=core.take_for(self.catalog,n,h,num,u)
        if not take or not take.get(kind) or core.identity(take[kind]['path'])!=core.identity(path):
            self.notice('No assignments');return
        iid=f'u:{n}:{h}:{u}' if u else f't:{n}:{h}'
        if not self.scene_tree.exists(iid):
            self.sync_filter=self.take_filter='any'
            self.only_unsynced_var.set(False);self.only_empty_var.set(False)
            self._configure_filter_choices()
        self.active_side=kind
        self.refresh_scene_tree(iid)
        self.last_take_number=num
        self.render_takes(select_take=num)
        self.scene_tree.focus(iid)
        self.media_tree.focus_set()
        self.queue_save_session()

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
            self._propagate_related_links(*target)
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
        if not row:return
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
        self._hide_link_tooltip()
        self._link_tooltips.clear()
        self.scene_tree.delete(*self.scene_tree.get_children())
        for scene in self.catalog['scenes']:
            all_takes=[t for sh in scene['shots'] for t in self._all_takes(sh)]
            visible=[]
            for sh in scene['shots']:
                all_shot=self._all_takes(sh)
                subs=[sub for sub in sh.get('subshots',[]) if self._filter_matches(sub['takes'])]
                if self._filter_matches(all_shot) or subs:
                    visible.append((sh,subs))
            if not self._filter_matches(all_takes) and not visible:
                continue
            all_takes=[t for sh in scene['shots'] for t in self._all_takes(sh)]
            videos=sum(bool(t.get('video')) for t in all_takes)
            audios=sum(bool(t.get('audio')) for t in all_takes)
            status=scene_sync.node_status(all_takes)
            sid=f"s:{scene['number']}"
            empty=core.empty_scene(scene)
            tags=('empty_scene',) if empty and self.highlight_empty_var.get() else ('sync_bad',) if status in ('KO','REVIEW') else ('scene',)
            link_mark = self._linked_suffix(scene['number'])
            self.scene_tree.insert('','end',iid=sid,
                text=str(scene['number']).zfill(self.catalog['settings']['padding']),
                values=(str(scene['number']).zfill(self.catalog['settings']['padding']), "", "", f"{videos}V / {audios}A"+link_mark,self._sync_label(status)),tags=tags)
            self._remember_link_tooltip(sid,scene['number'])
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
                link_mark = self._linked_suffix(scene['number'],sh['number'])
                self.scene_tree.insert('','end',iid=tid,
                    text=str(scene['number']).zfill(padding),
                    values=(str(scene['number']).zfill(padding),str(sh['number']).zfill(padding), "", f"{v}V / {a}A"+link_mark,self._sync_label(status)),tags=tag)
                self._remember_link_tooltip(tid,scene['number'],sh['number'])
                for sub in subs:
                    status=scene_sync.node_status(sub['takes'])
                    sub_empty=core.empty_subshot(sub)
                    vid=sum(bool(t.get('video')) for t in sub['takes'])
                    aud=sum(bool(t.get('audio')) for t in sub['takes'])
                    uid=f"u:{scene['number']}:{sh['number']}:{sub['id']}"
                    prefix='○  ' if sub_empty and self.highlight_empty_var.get() else '◦  '
                    tag=('empty_subshot',) if sub_empty and self.highlight_empty_var.get() else ('sync_bad',) if status in ('KO','REVIEW') else ('subshot',)
                    link_mark = self._linked_suffix(scene['number'],sh['number'],sub['id'])
                    self.scene_tree.insert('','end',iid=uid,
                        text=str(scene['number']).zfill(padding),
                        values=(str(scene['number']).zfill(padding),str(sh['number']).zfill(padding),sub['name'],f"{vid}V / {aud}A"+link_mark,self._sync_label(status)),tags=tag)
                    self._remember_link_tooltip(uid,scene['number'],sh['number'],sub['id'])
        if select and self.scene_tree.exists(select):
            self.scene_tree.selection_set(select);self.scene_tree.see(select)
        n_scene=sum(core.empty_scene(s) for s in self.catalog['scenes'])
        n_shot=sum(core.empty_shot(sh) for s in self.catalog['scenes'] for sh in s['shots'])
        n_sub=sum(core.empty_subshot(u) for s in self.catalog['scenes'] for sh in s['shots'] for u in sh.get('subshots',[]))
        unsynced=sum(scene_sync.needs_sync_attention(t)
                     for s in self.catalog['scenes'] for sh in s['shots'] for t in self._all_takes(sh))
        self.scene_count_var.set(self.tr(f'{n_scene} scene · {n_shot} shot · {n_sub} sotto-shot senza file')+f'  |  {unsynced} sync pending/review/KO')
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
                                 fmt(v,VIDEO),self.rating_code(v['quality']) if v else '—',fmt(a,AUDIO),self.rating_code(a['quality']) if a else '—',
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
        try:core.ensure_media_target(self.catalog,*target,self.selected_subshot_id())
        except core.CatalogError as exc:
            messagebox.showinfo(self.tr('Sub-shot required'),self.tr(str(exc)),parent=self.root)
            return
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
        self._propagate_related_links(target[0], target[1], self.selected_subshot_id())
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
            self._propagate_related_links(target[0], target[1], self.selected_subshot_id())
            self.last_take_number=new
            self.refresh_scene_tree(self.last_tree_selection);self.changed()
        except core.CatalogError as exc:
            self.undo_stack.pop();messagebox.showerror('Numero non valido',str(exc),parent=self.root)

    def delete_take(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        if not messagebox.askyesno('Elimina ciak',f'Eliminare il ciak {num} e le sue associazioni?\nI file originali non saranno toccati.',parent=self.root):return
        self.snapshot();core.remove_take(self.catalog,*target,num,subshot_id=self.selected_subshot_id())
        self._propagate_related_links(target[0], target[1], self.selected_subshot_id())
        self.last_take_number=None
        self.refresh_scene_tree(self.last_tree_selection);self.changed()

    def add_scene(self):
        self.commit_notes();self.snapshot()
        n=core.add_scene(self.catalog)
        core.add_shot(self.catalog,n,1)
        self._propagate_related_links(n)
        self.refresh_scene_tree(f't:{n}:1');self.changed()
        self.notice(f'Creata {core.label(self.catalog,n,1)}. Puoi trascinare i file sullo shot.')

    def add_shot(self):
        self.commit_notes()
        n,_=self.selected_ids()
        if n is None:messagebox.showinfo('Scena richiesta','Seleziona prima una scena o un suo shot.',parent=self.root);return
        self.snapshot()
        h=core.add_shot(self.catalog,n)
        self._propagate_related_links(n)
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
            self._propagate_related_links(target[0], target[1], None)
            self.refresh_scene_tree(f'u:{target[0]}:{target[1]}:{uid}')
            self.changed()
        except core.CatalogError as exc:
            if self.undo_stack:self.undo_stack.pop()
            messagebox.showerror('Nome non valido',str(exc),parent=self.root)

    def clear_selected_content(self):
        target=self.tree_target()
        if target is None:return
        self.commit_notes()
        targets=core.clear_take_targets(self.catalog,*target)
        count=sum(len(node['takes']) for node in targets)
        if not count:
            self.notice('No takes to clear.');return
        name=self._target_text(*target)
        message=self.tr('Remove all takes from this item, its descendants and linked equivalents?')
        message+='\n\n'+name+'\n'+self.tr('Take entries to remove:')+f' {count}'
        message+='\n\n'+self.tr('Structure, node descriptions and link groups are preserved. Original media files are not deleted. Undo is available.')
        if not messagebox.askyesno(self.tr('Clear content…'),message,parent=self.root):return
        self.snapshot()
        core.clear_take_content(self.catalog,*target)
        self.last_take_number=None
        self._editing_take_target=None
        self.refresh_scene_tree(self.last_tree_selection)
        self.changed();self.notice('Content cleared. Original media unchanged.')

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
        elif u:
            core.remove_subshot(self.catalog,n,h,u); self._propagate_related_links(n,h,None); sel=f't:{n}:{h}'
        else:
            core.remove_shot(self.catalog,n,h); self._propagate_related_links(n); sel=f's:{n}'
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
            affected=[]
            for obj,key,value in updates:
                obj[key]=value
            if target:
                affected.append(target)
            if take_key:
                affected.append(take_key[:3])
            for item in affected:
                self._propagate_related_links(*item)
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
        try:core.ensure_media_target(self.catalog,n,h,sub)
        except core.CatalogError as exc:
            messagebox.showinfo(self.tr('Sub-shot required'),self.tr(str(exc)),parent=self.root)
            return
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
            self._propagate_related_links(n, h, sub)
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
        self._propagate_related_links(target[0], target[1], self.selected_subshot_id())
        self.refresh_scene_tree(self.last_tree_selection);self.changed()
        self.notice(f'Ciak {num} · {self.active_side}: {self.rating_code(quality)} = {self.rating_name(quality)}.')
        return 'break'

    def remove_media(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if not target or num is None:return
        take=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        if take[self.active_side] is None:
            self.notice('Nessun file su questo lato.');return
        self.snapshot()
        core.remove_media(self.catalog,*target,num,self.active_side,self.selected_subshot_id())
        self._propagate_related_links(target[0], target[1], self.selected_subshot_id())
        self.last_take_number=num if core.take_for(self.catalog,*target,num,self.selected_subshot_id()) else None
        self.refresh_scene_tree(self.last_tree_selection);self.changed()
        self.notice('Collegamento eliminato; nessun file originale modificato.')

    def rating_code(self,quality):
        return {'B':'G','R':'R','S':'X'}[quality] if self.language=='en' else quality

    def rating_name(self,quality):
        return {'B':'Good','R':'Reserve','S':'Reject'}[quality] if self.language=='en' else core.QUALITIES[quality]

    def refresh_rating_labels(self):
        codes='/'.join(self.rating_code(q) for q in ('B','R','S'))
        for col in ('vq','aq'):self.media_tree.heading(col,text=codes)
        for q,btn in self.rating_buttons.items():btn.configure(text=f'{self.rating_code(q)} · {self.rating_name(q)}')

    def rating_shortcut(self,event):
        mapping={self.rating_code(q).lower():q for q in ('B','R','S')}
        key=event.keysym.lower()
        if key=='p' and not (event.state & 0xC):
            self.quick_review();return 'break'
        if key in mapping:return self.set_quality(mapping[key])

    def show_take_video_menu(self,event):
        row=self.media_tree.identify_row(event.y)
        if not row:return
        self.media_tree.selection_set(row);self.media_tree.focus(row)
        self.on_take_select()
        menu=self.take_video_menu
        menu.delete(0,'end')
        menu.add_command(label=self.tr('Play selected video (F4)'),command=lambda:self.root.after_idle(self.play_selected_video))
        menu.add_command(label=self.tr('Video player…'),command=lambda:self.root.after_idle(self.choose_video_player))
        menu.add_command(label=self.tr('Use system video player'),command=self.reset_video_player)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def choose_video_player(self):
        # Native dialogs must be opened after popup menus release their grabs.
        # Use a non-hidden parent and a single glob per file type on Windows.
        try:
            path=_filedialog.askopenfilename(parent=self.root,title=self.tr('Choose video player executable'),
                    initialdir=str(Path(self.video_player).parent) if self.video_player and Path(self.video_player).is_file() else str(Path.home()),
                    filetypes=[(self.tr('Programs'),'*.exe'),(self.tr('All files'),'*')] if sys.platform=='win32' else [(self.tr('All files'),'*')])
            if path:
                self.video_player=str(Path(path).resolve());self.queue_save_session()
                self.notice(self.tr('Video player:')+' '+self.video_player)
        except (OSError,tk.TclError,ValueError) as exc:
            messagebox.showerror(self.tr('Video player…'),str(exc),parent=self.root)

    def reset_video_player(self):
        self.video_player='';self.queue_save_session();self.notice('System video player selected.')

    def play_selected_video(self,event=None):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if target and num is not None:
            take=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
            if take and take.get('video'):
                self.launch_media(take['video']['path'],VIDEO);return 'break'
            self.notice('Select a video to play.');return 'break'
        paths=self.video_browser.selected_files()
        if paths:self.launch_media(paths[0],VIDEO)
        else:self.notice('Select a video to play.')
        return 'break'

    def launch_media(self,path,kind):
        p=str(Path(path).resolve())
        if not Path(p).is_file():messagebox.showerror('File non trovato',p,parent=self.root);return
        try:
            if sys.platform=='win32':
                # Frozen PyInstaller processes alter DLL lookup for child apps.
                # Temporarily restore the Windows default before launching.
                import ctypes
                kernel=ctypes.windll.kernel32
                buffer=ctypes.create_unicode_buffer(32768)
                n=kernel.GetDllDirectoryW(len(buffer),buffer)
                if n>=len(buffer):raise OSError('Cannot read Windows DLL search path')
                previous=buffer.value if n else None
                if not kernel.SetDllDirectoryW(None):raise ctypes.WinError()
                try:
                    if kind==VIDEO and self.video_player:
                        subprocess.Popen([self.video_player,p],shell=False)
                    else:os.startfile(p,'open')
                finally:kernel.SetDllDirectoryW(previous)
            elif kind==VIDEO and self.video_player:
                subprocess.Popen([self.video_player,p],shell=False)
            elif sys.platform=='darwin':subprocess.Popen(['open',p])
            else:subprocess.Popen(['xdg-open',p])
            self.notice(self.tr('Opening media:')+' '+Path(p).name)
        except (OSError,AttributeError,ValueError) as exc:
            self.notice('Unable to open media.')
            messagebox.showwarning('Impossibile aprire',str(exc),parent=self.root)

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
        self.launch_media(media['path'],self.active_side)

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
                old_method=(t.get('sync') or {}).get('method', 'waveform')
                upgrade=status in ('REVIEW','KO') and old_method not in ('manual',scene_sync.METHOD)
                if retry or status=='PENDING' or upgrade:
                    if retry or upgrade:t['sync']=None
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
                    # Never overwrite a manually verified alignment with a late worker result.
                    current=take.get('sync') or {}
                    if current.get('method')=='manual' and scene_sync.effective_status(take)=='OK':continue
                    take['sync']=copy.deepcopy(result)
                    changed=True
        if changed:
            for scene,shot,sub,container in core.iter_containers(self.catalog):
                if any(t.get('sync') for t in container['takes']):
                    self._propagate_related_links(scene['number'], shot['number'], sub['id'] if sub else None)
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

    def quick_review(self):
        self.edit_sync(quick=True)

    def edit_sync(self,quick=False):
        """Open a quick listening modal or precision editor."""
        self.commit_notes()
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
            current=core.take_for(self.catalog,*target,number,sub_id)
            if not current or not (current.get('video') and current.get('audio')) or \
                scene_sync.fingerprint(current['video']['path'],current['audio']['path'])!=signature:
                raise RuntimeError('Paired media changed while editing; reopen the sync editor.')
            self.snapshot()
            record=scene_sync.sync_record('OK',offset_seconds=offset,score=None,
                    method='manual',signature=signature,
                    error='Manually approved after listening; check long-take drift.')
            record['manual_verified']=True
            current['sync']=record
            self._propagate_related_links(target[0], target[1], sub_id)
            self.changed()
            self.refresh_scene_tree()
            self.notice('Manual synchronization saved. XML export will use the verified offset.')
            self.root.after_idle(self.media_tree.focus_set)

        record=take.get('sync') or {}
        if quick and record.get('offset_seconds') is not None and record.get('signature')==signature:
            def full_editor():
                SyncEditor(self.root,video,audio,record,approve,language=self.language)
            QuickSyncReview(self.root,video,audio,record,approve,full_editor,language=self.language)
        else:
            if quick:self.notice('No suggested offset; open the sync editor.')
            SyncEditor(self.root,video,audio,record,approve,language=self.language)

    def sync_details(self):
        target=self.active_shot(quiet=True);num=self.selected_take()
        if target is None or num is None:return
        t=core.take_for(self.catalog,*target,num,self.selected_subshot_id())
        status=scene_sync.effective_status(t)
        record=t.get('sync') or {}
        fps=float(self.catalog.get('settings',{}).get('timeline_fps',25))
        offset=record.get('offset_seconds')
        quant_note='N/A'
        if offset is not None:
            aligned=round(float(offset)*fps)/fps
            quant_note=f'{(aligned-float(offset))*1000:+.1f} ms at {fps:g} fps'
        message=(f'{self.tr("Status:")} {status}\n{self.tr("Offset (audio source at video zero):")} '
            f'{offset} s\nCorrelation score: {record.get("score")}\n'
            f'{self.tr("Method:")} {record.get("method", "waveform")}\n'
            f'Windows verified: {record.get("windows_verified", "N/A")}\n'
            f'Window spread: {record.get("window_spread_ms", "N/A")} ms\n'
            f'XML rounding error: {quant_note}\n'
            f'{self.tr("Note:")} {record.get("error", "") or "None"}\n\n'
            'OK indicates agreement of several acoustic windows; verify final playback in Resolve.')
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
        self._hide_link_tooltip()
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
    if sys.platform == 'win32':
        # Windows uses the explicit application ID for taskbar grouping and icon lookup.
        # The executable itself carries sceneslate_logo.ico through PyInstaller --icon.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SceneSlate.Desktop.3')
        except (AttributeError,OSError):
            pass
    root=tk.Tk();app=SceneSlateApp(root)
    app.startup(args.project)
    root.after(850,app.maybe_prompt_ffmpeg)
    root.mainloop()


if __name__=='__main__':main()
