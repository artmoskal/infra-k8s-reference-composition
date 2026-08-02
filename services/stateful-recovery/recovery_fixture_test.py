import pathlib
import tempfile
import unittest

import recovery_fixture


class RecordStoreTest(unittest.TestCase):
    def test_round_trip_is_deterministic_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "records.json"
            recovery_fixture.write_records({"z": "last", "a": "first"}, path)
            self.assertEqual({"a": "first", "z": "last"}, recovery_fixture.read_records(path))
            self.assertEqual(b'{"a":"first","z":"last"}\n', path.read_bytes())
            self.assertEqual([], list(path.parent.glob(".records-*")))

    def test_non_string_store_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "records.json"
            path.write_text('{"key": 3}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                recovery_fixture.read_records(path)


if __name__ == "__main__":
    unittest.main()
