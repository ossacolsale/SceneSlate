"""Regression tests: structural edits are local even within linked groups."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import scene_core as core

class LocalStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.v=Path(self.temp.name)/'original.mov';self.v.touch()
        self.extra=Path(self.temp.name)/'angle.mov';self.extra.touch()
        self.c=core.new_catalog()
        for n in (8,9):
            core.add_scene(self.c,n)
            for h in (3,6):
                core.add_shot(self.c,n,h)
        core.add_media(self.c,8,3,self.v,'video')
        core.configure_links(self.c,8,3,None,[core.node_ref(8,6),core.node_ref(9,3)])

    def test_extra_angle_never_propagates_but_direct_takes_do(self):
        u=core.add_subshot(self.c,8,3,'+')
        core.add_media(self.c,8,3,self.extra,'video',subshot_id=u)
        core.propagate_links(self.c,8,3,u)
        core.propagate_links(self.c,8,3)
        for n,h in ((8,6),(9,3)):
            node=core.shot_for(self.c,n,h)
            self.assertFalse(node['subshots'])
            self.assertEqual(len(node['takes']),1)
        core.take_for(self.c,8,3,1)['description']='direct'
        core.propagate_links(self.c,8,3)
        self.assertEqual(core.take_for(self.c,9,3,1)['description'],'direct')
        self.assertEqual(len(core.subshot_for(self.c,8,3,u)['takes']),1)
        self.assertEqual(len(core.media_assignments(self.c,self.extra,'video')),1)
        core.validate(self.c)

    def test_scene_links_preserve_local_nodes_and_explicit_subshot_links(self):
        u=core.add_subshot(self.c,8,3,'A')
        w=core.add_subshot(self.c,9,3,'Wide')
        core.add_media(self.c,8,3,self.extra,'video',subshot_id=u)
        core.configure_links(self.c,8,3,u,[core.node_ref(9,3,w)])
        gid=core.subshot_for(self.c,9,3,w)['link_group']
        core.add_shot(self.c,8,11)
        core.configure_links(self.c,8,member_refs=[core.node_ref(9)])
        self.assertIsNone(core.shot_for(self.c,9,11))
        self.assertEqual(core.subshot_for(self.c,9,3,w)['link_group'],gid)
        self.assertEqual(core.subshot_for(self.c,9,3,w)['name'],'Wide')
        core.take_for(self.c,8,3,1,u)['description']='linked angle'
        core.propagate_links(self.c,8,3,u)
        self.assertEqual(core.take_for(self.c,9,3,1,w)['description'],'linked angle')
        core.validate(self.c)

    def test_clear_angle_does_not_touch_same_name_in_parent_group(self):
        u=core.add_subshot(self.c,8,3,'+')
        w=core.add_subshot(self.c,8,6,'+')
        for h,uid in ((3,u),(6,w)):
            core.add_media(self.c,8,h,self.extra,'video',subshot_id=uid)
        self.assertEqual(core.clear_take_content(self.c,8,3,u),1)
        self.assertEqual(len(core.subshot_for(self.c,8,6,w)['takes']),1)
        self.assertEqual(len(core.shot_for(self.c,8,3)['takes']),1)

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Tk display required')
class LocalRepairGuiTests(unittest.TestCase):
    def test_blank_name_cancel_confirm_undo_and_no_recreation(self):
        import tkinter as tk
        from scene_slate import SceneSlateApp
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SCENESLATE_CONFIG_DIR':d}):
            root=tk.Tk();app=SceneSlateApp(root)
            try:
                v=Path(d)/'v.mov';v.touch()
                for h in (3,6):
                    if h==3:core.add_scene(app.catalog,8)
                    core.add_shot(app.catalog,8,h)
                    core.add_media(app.catalog,8,h,v,'video')
                core.configure_links(app.catalog,8,3,None,[core.node_ref(8,6)])
                u=core.add_subshot(app.catalog,8,3,'+')
                w=core.add_subshot(app.catalog,8,6,'+')
                core.add_media(app.catalog,8,3,v,'video',subshot_id=u)
                core.add_media(app.catalog,8,6,v,'video',subshot_id=w)
                iid=f'u:8:6:{w}'
                app.refresh_scene_tree(iid)
                with patch('scene_slate.simpledialog.askstring',return_value=''),patch('scene_slate.messagebox.askyesno',return_value=False):
                    app.renumber()
                self.assertIsNotNone(core.subshot_for(app.catalog,8,6,w))
                with patch('scene_slate.simpledialog.askstring',return_value='  '),patch('scene_slate.messagebox.askyesno',return_value=True):
                    with patch.object(app.scene_tree,'identify_row',return_value=iid):
                        self.assertEqual(app.rename_tree_row(Mock(y=10)),'break')
                self.assertIsNone(core.subshot_for(app.catalog,8,6,w))
                self.assertIsNotNone(core.subshot_for(app.catalog,8,3,u))
                self.assertEqual(len(core.shot_for(app.catalog,8,6)['takes']),1)
                self.assertTrue(v.exists())
                core.propagate_links(app.catalog,8,3)
                self.assertFalse(core.shot_for(app.catalog,8,6)['subshots'])
                app.undo()
                self.assertIsNotNone(core.subshot_for(app.catalog,8,6,w))
                core.validate(app.catalog)
            finally:
                app._sync_worker.close();root.destroy()
