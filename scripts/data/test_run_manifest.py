import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from run_manifest import simulation_run, validation_results


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "out"
        self.output.mkdir()
        self.config = self.root / "config.json"
        self.config.write_text('{"dt":30,"nested":{"access_token":"hidden-value"}}')

    def start(self, inputs=(), **kwargs):
        return simulation_run(self.root, "test", inputs, [self.output], [self.config], **kwargs)

    def final(self, run):
        return json.loads((self.root / "data/runs" / run["run_id"] / "manifest.json").read_text())

    def test_creation_hashes_and_unique_identity(self):
        stale = self.output / "stale"
        stale.touch()
        with self.start() as first:
            (self.output / "a.bin").write_bytes(b"abc")
            validation_results(first, {"match": True})
        with self.start() as second:
            pass
        self.assertNotEqual(first["run_id"], second["run_id"])
        doc = self.final(first)
        self.assertEqual(doc["status"], "succeeded")
        self.assertEqual(doc["inputs"][0]["sha256"], hashlib.sha256(self.config.read_bytes()).hexdigest())
        self.assertEqual([f["path"] for f in doc["outputs"]], ["out/a.bin"])
        self.assertEqual(doc["outputs"][0]["sha256"], hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(doc["outputs"][0]["run_id"], first["run_id"])
        self.assertEqual(self.final(second)["validations"], [])

    def test_missing_file_failed_status(self):
        with self.assertRaises(FileNotFoundError):
            with self.start([self.root / "absent.tif"]):
                self.fail("run must not start")
        manifest = next((self.root / "data/runs").glob("*/manifest.json"))
        doc = json.loads(manifest.read_text())
        self.assertEqual(doc["status"], "failed")
        self.assertIsNone(doc["inputs"][-1]["sha256"])

    def test_secrets_and_partial_failure(self):
        with self.assertRaises(ValueError):
            with self.start() as run:
                (self.output / "partial").touch()
                raise ValueError("secret in exception: hidden-value")
        doc = self.final(run)
        self.assertNotIn("hidden-value", json.dumps(doc))
        self.assertEqual(doc["error"]["type"], "ValueError")
        self.assertEqual(len(doc["outputs"]), 1)

    def test_existing_record_protected_and_false_check_retained(self):
        with self.start() as run:
            validation_results(run, {"mass_balance": False})
        doc = self.final(run)
        self.assertEqual(doc["status"], "validation_failed")
        with self.assertRaises(FileExistsError):
            with self.start(run_id=run["run_id"]):
                pass
        self.assertEqual(self.final(run), doc)
