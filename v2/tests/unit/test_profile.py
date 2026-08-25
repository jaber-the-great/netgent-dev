"""BrowserProfile: nothing injected, nothing spoofed by default; every knob explicit."""

import platform
import sys

from netgent.browser.profile import BrowserProfile, user_agent_metadata


def test_default_profile_sets_nothing_but_the_channel():
    p = BrowserProfile.default()
    assert p.launch_kwargs(headless=True) == {"headless": True, "args": [], "channel": "chrome"}
    assert p.context_kwargs(headless=True) == {}
    assert p.context_kwargs(headless=False) == {"no_viewport": True}


def test_bare_profile_is_bundled_chromium():
    assert "channel" not in BrowserProfile.bare().launch_kwargs(headless=True)


def test_headless_user_agent_is_only_passed_as_a_launch_flag():
    ua = BrowserProfile.headless_user_agent("151.0.7922.175")
    assert "HeadlessChrome" not in ua and "Chrome/151.0.0.0" in ua
    kwargs = BrowserProfile.default().launch_kwargs(headless=True, user_agent=ua)
    assert kwargs["args"] == [f"--user-agent={ua}"]
    assert "user_agent" not in BrowserProfile.default().context_kwargs(headless=True)


def test_explicit_axes_are_passed_through():
    p = BrowserProfile(locale="de-DE", timezone_id="Europe/Berlin", viewport=(1280, 800), storage_state="s.json")
    assert p.context_kwargs(headless=False) == {
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
        "viewport": {"width": 1280, "height": 800},
        "storage_state": "s.json",
    }


def test_user_agent_metadata_completes_the_hints_from_binary_and_host():
    brands = [{"brand": "Not=A?Brand", "version": "99"}, {"brand": "Google Chrome", "version": "151"}]
    meta = user_agent_metadata("151.0.7922.175", brands, "macOS")
    assert meta["brands"] == brands
    assert meta["fullVersionList"] == [
        {"brand": "Not=A?Brand", "version": "99.0.0.0"},
        {"brand": "Google Chrome", "version": "151.0.7922.175"},
    ]
    assert meta["architecture"] == ("arm" if platform.machine().lower() in ("arm64", "aarch64") else "x86")
    assert meta["bitness"] == "64" and meta["mobile"] is False
    if sys.platform == "darwin":
        assert meta["platformVersion"] == platform.mac_ver()[0]
