import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan_secrets  # noqa: E402


def hit(text: str) -> bool:
    return any(rx.search(text) for rx in scan_secrets.PATTERNS.values())


def test_finds_real_looking_keys():
    assert hit("key = sk-ant-" + "a1B2c3D4e5F6g7H8i9J0k1L2")
    assert hit("AKIA" + "ABCDEFGHIJKLMNOP")
    assert hit("-----BEGIN RSA " + "PRIVATE KEY-----")


def test_ignores_plain_text():
    assert not hit("Set ANTHROPIC_API_KEY in your environment file.")


def test_a_real_key_on_a_line_that_says_example_is_still_reported():
    key = "sk-ant-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    assert scan_secrets.scan_line(f"# example of a real key: {key}") == ["Anthropic key"]


def test_a_fake_marker_inside_the_value_is_allowed():
    assert scan_secrets.scan_line('secret = "test-only-' + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6" + '"') == []
