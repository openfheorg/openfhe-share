from __future__ import annotations

import base64
import json
import unittest
import zlib
from urllib.parse import parse_qs, urlsplit

from share_desktop.services.share_launch import (
    SHARE_LAUNCH_PAYLOAD_VERSION,
    build_share_launch_url,
    encode_share_launch_payload,
)


def decode_launch_value(value: str) -> dict[str, object]:
    padding = "=" * ((4 - len(value) % 4) % 4)
    compressed = base64.urlsafe_b64decode(value + padding)
    return json.loads(zlib.decompress(compressed).decode("utf-8"))


class ShareLaunchTests(unittest.TestCase):
    def test_explore_payload_contains_username_only(self) -> None:
        encoded = encode_share_launch_payload(" initiator ")

        self.assertEqual(
            decode_launch_value(encoded),
            {
                "v": SHARE_LAUNCH_PAYLOAD_VERSION,
                "username": "initiator",
            },
        )

    def test_results_payload_contains_username_and_nvflare_job_id(self) -> None:
        job_id = "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
        encoded = encode_share_launch_payload("initiator", job_id)

        self.assertEqual(
            decode_launch_value(encoded),
            {
                "v": SHARE_LAUNCH_PAYLOAD_VERSION,
                "username": "initiator",
                "nvflare_job_id": job_id,
            },
        )

    def test_payload_uses_url_safe_unpadded_base64(self) -> None:
        encoded = encode_share_launch_payload("initiator")

        self.assertNotIn("+", encoded)
        self.assertNotIn("/", encoded)
        self.assertFalse(encoded.endswith("="))

    def test_utf8_username_round_trips_like_json_stringify(self) -> None:
        encoded = encode_share_launch_payload("josé")

        self.assertEqual(decode_launch_value(encoded)["username"], "josé")

    def test_build_url_preserves_unrelated_query_and_fragment(self) -> None:
        url = build_share_launch_url(
            "https://share.example.org/app?s=0&theme=dark#results",
            "initiator",
        )
        parts = urlsplit(url)
        query = parse_qs(parts.query)

        self.assertEqual(parts.path, "/app")
        self.assertEqual(parts.fragment, "results")
        self.assertEqual(query["s"], ["0"])
        self.assertEqual(query["theme"], ["dark"])
        self.assertEqual(
            decode_launch_value(query["launch"][0]),
            {"v": SHARE_LAUNCH_PAYLOAD_VERSION, "username": "initiator"},
        )

    def test_build_url_replaces_stale_launch_fields(self) -> None:
        job_id = "54fa4d0e-a405-42eb-82f8-bb4dc4f7efd3"
        url = build_share_launch_url(
            "https://share.example.org/?launch=old&username=old&nvflare_job_id=old&s=0",
            "initiator",
            job_id,
        )
        query = parse_qs(urlsplit(url).query)

        self.assertEqual(query["s"], ["0"])
        self.assertNotIn("username", query)
        self.assertNotIn("nvflare_job_id", query)
        self.assertEqual(len(query["launch"]), 1)
        self.assertEqual(decode_launch_value(query["launch"][0])["nvflare_job_id"], job_id)

    def test_invalid_urls_and_missing_username_are_rejected(self) -> None:
        cases = [
            ("", "initiator"),
            ("share.example.org", "initiator"),
            ("file:///tmp/share", "initiator"),
            ("https://share.example.org", ""),
        ]

        for share_url, username in cases:
            with self.subTest(share_url=share_url, username=username):
                with self.assertRaises(ValueError):
                    build_share_launch_url(share_url, username)


if __name__ == "__main__":
    unittest.main()
