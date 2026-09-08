import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from resources import GIB, check_space


class StorageGuardTest(unittest.TestCase):
    def test_configured_volume_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"KOKORIKO_STORAGE_PATH": directory}):
                result = check_space(minimum_free_gib=0)
            self.assertEqual(result["volume"], str(Path(directory).resolve()))
            self.assertGreater(result["free_bytes"], 0)

    def test_low_space_stops_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "completed.json"
            marker.write_text("preserve")
            with (
                patch.dict(os.environ, {"KOKORIKO_STORAGE_PATH": directory}),
                patch("resources.shutil.disk_usage", return_value=shutil._ntuple_diskusage(20 * GIB, 11 * GIB, 9 * GIB)),
            ):
                with self.assertRaises(RuntimeError):
                    check_space()
            self.assertEqual(marker.read_text(), "preserve")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
