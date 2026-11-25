from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = ROOT / "skills/askovo/scripts/connectors"
if str(CONNECTORS) not in sys.path:
    sys.path.insert(0, str(CONNECTORS))


def load_module():
    name = "askovo_arctic_pagination_test"
    spec = importlib.util.spec_from_file_location(name, CONNECTORS / "collect_arctic_reddit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def comment(comment_id, created):
    return {
        "id": comment_id, "body": "A substantive research comment", "author": "author",
        "created_utc": created, "subreddit": "python", "permalink": "/r/python/comments/%s" % comment_id,
    }


class ArcticPaginationTest(unittest.TestCase):
    def setUp(self):
        self.arctic = load_module()

    def test_short_page_stops_after_one_request(self):
        with mock.patch.object(self.arctic.common, "request_json",
                               return_value={"data": [comment("a", 200), comment("b", 100)]}) as fetch:
            rows = self.arctic.collect(["python"], 0, 10, 3, 0, 1, "run", None)
        self.assertEqual(2, len(rows))
        self.assertEqual(1, fetch.call_count)

    def test_full_page_advances_before_and_empty_page_stops(self):
        responses = [{"data": [comment("a", 200), comment("b", 100)]}, {"data": []}]
        with mock.patch.object(self.arctic.common, "request_json", side_effect=responses) as fetch:
            rows = self.arctic.collect(["python"], 0, 10, 2, 0, 1, "run", None)
        self.assertEqual(2, len(rows))
        self.assertEqual(2, fetch.call_count)
        second_url = fetch.call_args_list[1].args[0]
        self.assertEqual(["99"], parse_qs(urlparse(second_url).query)["before"])

    def test_repeated_page_cursor_stops_instead_of_repeating_same_url(self):
        page = {"data": [comment("a", 200), comment("b", 100)]}
        with mock.patch.object(self.arctic.common, "request_json", side_effect=[page, page]) as fetch:
            rows = self.arctic.collect(["python"], 0, 10, 2, 0, 1, "run", None)
        self.assertEqual(2, len(rows))
        self.assertEqual(2, fetch.call_count)


if __name__ == "__main__":
    unittest.main()
