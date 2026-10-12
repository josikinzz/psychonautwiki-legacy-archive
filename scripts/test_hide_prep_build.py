"""Exercise the actual Vercel command without git-only preserved originals."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'vercel.json').is_file())
VERCEL = json.loads((ROOT / 'vercel.json').read_text())
SCRIPT = Path(shlex.split(VERCEL['buildCommand'])[1])
PW = SCRIPT == Path('scripts/hide_prep.py')
CONFIG = Path('hide-prep-config.json' if PW else 'archive/archive-config.json')
POLICY = json.loads((ROOT / CONFIG).read_text())
ROUTE = POLICY['hiddenRoutes' if PW else 'hiddenPostRoutes'][0]


class VercelBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in (SCRIPT, CONFIG, Path('vercel.json')):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        self.output = self.root / VERCEL['outputDirectory']
        self.output.mkdir(parents=True)
        (self.output / 'index.html').write_text('<html><body>Visible archive</body></html>')
        # hidden/ is deliberately absent, exactly as after .vercelignore filtering.

    def run_script(self, args):
        return subprocess.run([sys.executable, '-I', '-S', str(SCRIPT), *args],
                              cwd=self.root, capture_output=True, text=True)

    def build(self):
        return self.run_script(shlex.split(VERCEL['buildCommand'])[2:])

    def test_configured_build_passes_without_preservation_files(self):
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / 'hidden').exists())

    def test_local_check_still_requires_preserved_originals(self):
        result = self.run_script(['--check'])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('missing original:', result.stderr)

    def test_publication_check_still_rejects_hidden_routes_and_links(self):
        target = self.output / ROUTE.strip('/') / 'index.html'
        target.parent.mkdir(parents=True)
        target.write_text('<html>Hidden preparation</html>')
        (self.output / 'index.html').write_text('<a href="' + ROUTE + '">hidden</a>')
        (self.output / 'search.json').write_text(json.dumps([['hidden', ROUTE]]))
        result = self.run_script(['--build', '--check'])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        for error in ('public hidden route:', 'hidden link:', 'hidden JSON route:'):
            self.assertIn(error, result.stderr)

    def test_build_removes_reintroduced_pages_and_links(self):
        target = self.output / ROUTE.strip('/') / 'index.html'
        target.parent.mkdir(parents=True)
        target.write_text('<html>Hidden preparation</html>')
        (self.output / 'index.html').write_text('<a href="' + ROUTE + '">hidden</a>')
        (self.output / 'search.json').write_text(json.dumps([['hidden', ROUTE]]))
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(target.exists())
        self.assertNotIn(ROUTE, (self.output / 'index.html').read_text())
        self.assertEqual(json.loads((self.output / 'search.json').read_text()), [])
        self.assertTrue((self.root / 'hidden/pages' / ROUTE.strip('/') / 'index.html').exists())


if __name__ == '__main__':
    unittest.main()
