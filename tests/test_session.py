import os
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scene_core as core
import scene_session as session


class SessionAndFiltersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_session_state_saved_independently_and_atomically(self):
        state = {'version': 2, 'last_catalog': str(self.root / 'movie.json'),
                 'video': {'directory': '/tmp/media', 'selected_files': ['/tmp/media/c001.mov']}}
        session.write_state(state, self.root)
        self.assertEqual(session.read_state(self.root), state)
        self.assertEqual(list(self.root.glob('*.tmp')), [])
        (self.root / 'session.json').write_text('{broken', encoding='utf-8')
        self.assertEqual(session.read_state(self.root), {})

    def test_unassigned_paths_and_empty_filter(self):
        catalog = core.new_catalog()
        core.add_scene(catalog, 1); core.add_shot(catalog, 1, 1)
        core.add_shot(catalog, 1, 2)
        core.add_scene(catalog, 2); core.add_shot(catalog, 2, 1)
        core.add_scene(catalog, 3)  # zero shots also counts as empty
        f = self.root / 'v.mov'; f.write_bytes(b'v')
        core.add_media(catalog, 1, 2, f, 'video')
        self.assertEqual(core.assigned_paths(catalog, 'video'), {core.identity(f)})
        self.assertEqual(core.assigned_paths(catalog, 'audio'), set())
        self.assertFalse(core.empty_scene(catalog['scenes'][0]))
        self.assertTrue(core.empty_scene(catalog['scenes'][1]))
        scene_rows = list(core.scenes_for_display(catalog, True))
        self.assertEqual([(s['number'], [sh['number'] for sh in shots]) for s, shots in scene_rows],
                         [(1, [1]), (2, [1]), (3, [])])

    def test_sort_creation_and_fallback(self):
        class Stat:
            def __init__(self, birth, modify, creation=None):
                self.st_ctime = birth
                self.st_mtime = modify
                if creation is not None:self.st_birthtime = creation
        self.assertEqual(core.birth_timestamp(Stat(10, 20), 'win32'), (10, True))
        self.assertEqual(core.birth_timestamp(Stat(10, 20), 'linux'), (20, False))
        self.assertEqual(core.birth_timestamp(Stat(10, 20, 17), 'linux'), (17, True))
        a, b = self.root / 'A.mov', self.root / 'B.mov'
        items = [(b, False, Stat(5, 9)), (a, False, Stat(1, 1))]
        self.assertEqual([x[0].name for x in core.sort_directory_entries(items, 'name_asc')], ['A.mov', 'B.mov'])
        self.assertEqual([x[0].name for x in core.sort_directory_entries(items, 'name_desc')], ['B.mov', 'A.mov'])
        self.assertEqual([x[0].name for x in core.sort_directory_entries(items, 'created_asc')], ['A.mov', 'B.mov'])
        self.assertEqual([x[0].name for x in core.sort_directory_entries(items, 'created_desc')], ['B.mov', 'A.mov'])


if __name__ == '__main__': unittest.main()
