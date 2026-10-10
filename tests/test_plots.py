import json

from patreon_plex.harvest import post_text
from patreon_plex.library import set_episode_plot
from patreon_plex.titles import clean_plot


def para(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


def text(t, href=None):
    node = {"type": "text", "text": t}
    if href:
        node["marks"] = [{"type": "link", "attrs": {"href": href}}]
    return node


def test_post_text_drops_dividers_spacers_and_video_links():
    drive = "https://drive.google.com/file/d/1mOGpO4ug4F6ykI8_C9GWXJY41d4G9y2l/view?usp=sharing"
    doc = {"type": "doc", "content": [
        para(text("This was a fun one!")),
        para(text("----------------------------------------------------")),
        para(text(".")), para(text(".")),
        para({"type": "hardBreak"}),
        para(text("Part 1: "), text(drive[:40], href=drive)),
        para(text("Check my "), text("YouTube", href="https://youtube.com/channel/UC2o")),
    ]}
    assert post_text(json.dumps(doc)) == "This was a fun one!\n\nPart 1:\nCheck my YouTube"


def test_clean_plot_keeps_text_and_ellipses():
    raw = "Oh boy did he not prove the title! Lmao. ______________________\nMore soon...\n\n\n.\nBye"
    assert clean_plot(raw) == "Oh boy did he not prove the title! Lmao.\nMore soon...\n\nBye"


def test_no_text():
    assert post_text(None) == "" and clean_plot("-----\n.\n") == ""


def test_set_episode_plot(tmp_path):
    nfo = tmp_path / "ep.nfo"
    nfo.write_text('<?xml version="1.0" encoding="utf-8"?>\n<episodedetails><title>X</title><plot /></episodedetails>')
    assert set_episode_plot(nfo, "Hello ✨")
    assert "<plot>Hello ✨</plot>" in nfo.read_text()
    assert not set_episode_plot(nfo, "Hello ✨")
