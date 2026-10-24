"""video-lens-recs Takeout import: subscriptions by content shape, history ignored. No network."""
import json
import subprocess
import sys
import zipfile

import pytest

import recs_world
import takeout

A, B = recs_world.cid("takeoutalpha"), recs_world.cid("takeoutbeta")
EN_CSV = f"﻿Channel Id,Channel Url,Channel Title\n{A},http://www.youtube.com/channel/{A},Alpha Talks\n" \
         f"{B},http://www.youtube.com/channel/{B},\"Beta, the Channel\"\n"
DE_CSV = f"Kanal-ID,Kanal-URL,Kanaltitel\n{A},http://www.youtube.com/channel/{A},Alpha Talks\n"
# A history file that would import two "channels" if it were parsed as subscriptions.
HISTORY = json.dumps([{"header": "YouTube", "title": "Watched x", "titleUrl": "https://www.youtube.com/watch?v=abc",
                       "subtitles": [{"url": f"https://www.youtube.com/channel/{A}"}]}])


def make_zip(path, members: dict):
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return path


def test_english_csv_with_bom_and_quoted_title(tmp_path):
    z = make_zip(tmp_path / "takeout.zip", {
        "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": EN_CSV,
        "Takeout/YouTube and YouTube Music/history/watch-history.json": HISTORY,
    })
    res = takeout.import_takeout(z)
    assert [c["id"] for c in res["channels"]] == [A, B]
    assert res["channels"][1]["title"] == "Beta, the Channel"
    assert res["ignored"] == ["Takeout/YouTube and YouTube Music/history/watch-history.json"]
    assert res["export_date"]


def test_german_takeout_with_renamed_folders(tmp_path):
    z = make_zip(tmp_path / "takeout-de.zip", {
        "Takeout/YouTube und YouTube Music/Abos/Abos.csv": DE_CSV,
        "Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json": HISTORY,
    })
    res = takeout.import_takeout(z)
    assert [(c["id"], c["title"]) for c in res["channels"]] == [(A, "Alpha Talks")]
    assert res["ignored"] == ["Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json"]


def test_history_is_recognised_by_content_even_under_an_unknown_name(tmp_path):
    folder = tmp_path / "export"
    (folder / "x").mkdir(parents=True)
    (folder / "x" / "a.csv").write_text(EN_CSV, encoding="utf-8")
    (folder / "x" / "datei.json").write_text(HISTORY, encoding="utf-8")
    res = takeout.import_takeout(folder)
    assert len(res["channels"]) == 2
    assert res["ignored"] == ["x/datei.json"]


def test_old_json_and_html_formats():
    old = json.dumps([{"snippet": {"title": "Alpha Talks", "resourceId": {"kind": "youtube#channel", "channelId": A}}}])
    assert takeout.parse_json(old) == [{"id": A, "title": "Alpha Talks", "url": f"https://www.youtube.com/channel/{A}"}]
    page = f'<ul><li><a href="https://www.youtube.com/channel/{B}">Beta &amp; Co</a></li></ul>'
    assert takeout.parse_html(page)[0]["title"] == "Beta & Co"


def test_an_archive_without_subscriptions_is_a_named_error(tmp_path):
    z = make_zip(tmp_path / "empty.zip", {"Takeout/archive_browser.html": "<html></html>",
                                         "Takeout/YouTube/history/watch-history.json": HISTORY})
    with pytest.raises(takeout.TakeoutError) as e:
        takeout.import_takeout(z)
    assert e.value.code == "TAKEOUT_NO_SUBSCRIPTIONS"
    with pytest.raises(takeout.TakeoutError):
        takeout.import_takeout(tmp_path / "missing.zip")


def test_cli_import_sets_takeout_mode_and_reports_ignored_history(tmp_path, monkeypatch):
    recs_world.build(tmp_path, monkeypatch, mode="none")
    z = make_zip(tmp_path / "takeout.zip", {
        "Takeout/YouTube and YouTube Music/subscriptions/subscriptions.csv": EN_CSV,
        "Takeout/YouTube and YouTube Music/history/watch-history.json": HISTORY,
    })
    r = subprocess.run([sys.executable, str(recs_world.RECS_SCRIPTS / "recs.py"), "account", "import-takeout", str(z)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "IMPORTED: 2 subscriptions" in r.stdout
    assert "IGNORED:" in r.stdout and "never imported" in r.stdout
    assert "MODE: takeout" in r.stdout
    subs = json.loads((tmp_path / "data" / "video-lens" / "recs" / "subscriptions.json").read_text())
    assert subs["source"] == "takeout" and len(subs["channels"]) == 2
    # Nothing from the history file reached disk.
    assert "watch?v=abc" not in (tmp_path / "data").joinpath("video-lens", "recs", "subscriptions.json").read_text()
