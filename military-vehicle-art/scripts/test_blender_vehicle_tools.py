"""Contract tests; fixtures are NOT artwork-quality evidence."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name('blender_vehicle_tools.py')


class RigContractTests(unittest.TestCase):
    def test_missing_backend_has_actionable_error(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-S', str(SCRIPT), 'audit', '--blend', 'missing.blend', '--output', 'unused.json'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Blender Python', result.stderr)


def load_tools():
    spec = importlib.util.spec_from_file_location('vehicle_tools', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config():
    return {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [256, 256],
            'samples': 8, 'modes': ['clay', 'material', 'silhouette'],
            'preview_frame_heights': [96], 'views': [{'name': 'front', 'direction': [0, 1, 0]}],
            'frame': None, 'exposure': 0, 'world_strength': 0.35}


class ConfigTests(unittest.TestCase):
    def test_valid_rig_is_accepted(self):
        m = load_tools()
        self.assertTrue(hasattr(m, 'validate_config'), 'rig validation is not implemented')
        self.assertEqual(m.validate_config(config())['collection'], 'Vehicle')

    def test_invalid_rig_values_are_rejected(self):
        m = load_tools()
        self.assertTrue(hasattr(m, 'validate_config'), 'rig validation is not implemented')
        for key, value in [('resolution', [True, 256]), ('samples', 0), ('modes', []),
                           ('modes', ['made-up']), ('exposure', float('nan')),
                           ('views', [{'name': '../escape', 'direction': [0, 1, 0]}]),
                           ('views', [{'name': 'zero', 'direction': [0, 0, 0]}]),
                           ('views', [{'name': 'front', 'direction': [0, 1, 0], 'ortho_scale': -1}]),
                           ('views', [{'name': 'a', 'direction': [0, 1, 0]}, {'name': 'a', 'direction': [1, 0, 0]}]),
                           ('frame', {'center': [0, 0, 0], 'extent': 0}),
                           ('preview_frame_heights', [0]), ('world_strength', -1)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                m.validate_config(dict(config(), **{key: value}))

    def test_template_is_not_a_ready_rig(self):
        spec = importlib.util.spec_from_file_location('vehicle_tools', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'validate_config'), 'rig validation is not implemented')
        with self.assertRaises(ValueError):
            module.validate_config({'schema_version': 1, 'collection': None})


if __name__ == '__main__':
    unittest.main()
