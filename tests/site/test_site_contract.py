"""Site contract (contracts/site.md constraint table, tasks T060, T064, T065) on fixture results."""

from __future__ import annotations

import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest

from analogfinder import cli, errors, storage
from analogfinder.site import build

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "fixtures"
SAMPLE = json.loads((FX / "results_sample.json").read_text())
EMPTY = json.loads((FX / "results_empty.json").read_text())
INPUTS = json.loads((FX / "site_inputs_sample.json").read_text())
EXTERNAL = re.compile(r"^(https?:)?//", re.I)


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[tuple[str, str, str]] = []  # (tag, attr, value)
        self.tables: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for attr in ("src", "href"):
            if attr in a:
                self.refs.append((tag, attr, a[attr]))
        if tag == "table":
            self.tables.append(a)


def parse(path: Path) -> Refs:
    p = Refs()
    p.feed(path.read_text(encoding="utf-8"))
    return p


@pytest.fixture
def site(tmp_path):
    out = tmp_path / "site"
    build.render(SAMPLE, INPUTS, out, unvalidated=["calibration_not_run"])
    return out


def html_files(d: Path) -> list[Path]:
    return sorted(d.rglob("*.html"))


def test_layout_and_size(site):
    pid = SAMPLE["run_record"]["profile"]["id"]
    for rel in ("index.html", f"p/{pid}/index.html", "method.html", "about.html",
                "assets/style.css", "assets/map.js"):  # fmt: skip
        assert (site / rel).is_file(), rel
    ranked = [c for c in SAMPLE["candidates"] if c["status"] == "ranked"]
    for c in ranked:
        assert (site / "p" / pid / "c" / f"{c['area_id']}.html").is_file()
    first = sum(
        (site / f).stat().st_size for f in ("index.html", "assets/style.css", "assets/map.js")
    )
    assert first < 2 * 1024 * 1024  # SC-008
    assert (site / "assets/map.js").stat().st_size < 10 * 1024
    assert (site / "assets/style.css").stat().st_size < 20 * 1024


def test_no_external_requests(site):
    for f in html_files(site):
        for tag, attr, val in parse(f).refs:
            if tag in ("script", "link", "img", "source") or attr == "src":
                assert not EXTERNAL.match(val), (f, tag, val)
    css = (site / "assets/style.css").read_text()
    assert "@font-face" not in css and "@import" not in css


def test_internal_links_resolve_with_and_without_script(site):
    (site / "assets/map.js").unlink()  # content must not depend on the script
    for f in html_files(site):
        for tag, _attr, val in parse(f).refs:
            if tag == "script" or EXTERNAL.match(val) or val.startswith(("mailto:", "#")):
                continue
            target = (f.parent / val.split("#")[0]).resolve()
            assert target.is_file(), f"{f.relative_to(site)} -> {val}"


def test_fr036_fields_on_candidate_page(site):
    pid = SAMPLE["run_record"]["profile"]["id"]
    c = next(c for c in SAMPLE["candidates"] if c["rank"] == 1)
    html = (site / "p" / pid / "c" / f"{c['area_id']}.html").read_text()
    for text in ("Overall score", "Confidence", "Limiting criterion", "Area", "km²",
                 "Earth value", "Mars target", "Deviation", "Deviation / tolerance", "Score",
                 "Comparison", "Data source", "Limits of the analogy"):  # fmt: skip
        assert text in html, text
    for r in c["results"]:
        assert r["criterion_id"] in html
    assert "relative" in html and "not comparable" in html
    assert c["limiting_criterion"] in html and f"{100 * c['overall_score']:.1f}%" in html


def test_index_table_banners_and_profile_separation(site):
    html = (site / "index.html").read_text()
    assert "Not validated against known analogs" in html and "calibration_not_run" in html
    assert "Placeholder values" in html  # sample has placeholder_values: true
    assert "Deduplication not applied" in html
    assert "top 30 proven complete" in html
    ranked = [c for c in SAMPLE["candidates"] if c["status"] == "ranked"]
    assert html.count('class="marker') == len(ranked)
    for f in html_files(site):  # each results table holds one profile only
        for t in parse(f).tables:
            if "data-profile" in t:
                assert t["data-profile"] == SAMPLE["run_record"]["profile"]["id"]
    for f in html_files(site):  # banner on every page
        assert "Not validated against known analogs" in f.read_text(), f


def test_method_and_about_come_from_snapshot(site):
    method = (site / "method.html").read_text()
    for cid, w in INPUTS["profile"]["weights"].items():
        assert cid in method and build.num(w, 3) in method
    assert SAMPLE["run_record"]["percentile_population"]["name"] in method
    about = (site / "about.html").read_text()
    for s in INPUTS["sources"]:
        assert s["source_id"] in about
    for layer in INPUTS["grid"]["layers"]:
        assert layer["layer_id"] in about


def test_zero_candidates_message(tmp_path):
    build.render(EMPTY, INPUTS, tmp_path / "s")
    html = (tmp_path / "s" / "index.html").read_text()
    assert "No candidates" in html and "<table" not in html.split("No candidates")[1][:200]
    assert "Not validated" not in html  # no reasons passed


def test_preview_lists_bounds_without_ranks(tmp_path):
    res = json.loads(json.dumps(SAMPLE))
    res["run_record"]["refinement"]["stop"] = "skipped"
    for c in res["candidates"]:
        c.update(status="screened_only", rank=None, overall_score=None, upper_bound=0.7)
    build.render(res, INPUTS, tmp_path / "s")
    html = (tmp_path / "s" / "index.html").read_text()
    assert "Screening preview" in html and "Upper bound" in html and ">Rank<" not in html


# --- build_site / publish with a run directory --------------------------------------------


@pytest.fixture
def run_env(tmp_path):
    data, prof = tmp_path / "data", tmp_path / "profiles"
    rr = SAMPLE["run_record"]
    rdir = storage.run_dir(data, rr["run_id"])
    rdir.mkdir(parents=True)
    (rdir / "results.json").write_text(json.dumps(SAMPLE))
    (rdir / storage.COMPLETE).write_text("")
    (data / "runs" / "index.json").write_text(
        json.dumps(
            {
                f"{rr['profile']['id']}@{rr['profile']['version']}": [
                    {"run_id": rr["run_id"], "date": "2026-11-15T00:00:00+00:00"}
                ]
            }
        )  # fmt: skip
    )
    frozen = prof / "frozen" / f"{rr['profile']['id']}@{rr['profile']['version']}.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_text(json.dumps(INPUTS["profile"]))
    cfg = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfg)
    return data, prof, cfg, rr["run_id"], rdir


def test_build_site_reuses_and_ignores_later_config_edits(run_env):
    data, prof, cfg, run_id, _ = run_env
    d1, reused1 = build.build_site(data, cfg, prof, run_id)
    assert not reused1 and (d1 / "index.html").is_file() and (d1 / "site_inputs.json").is_file()
    about1 = (d1 / "about.html").read_text()
    sources = json.loads((cfg / "sources.json").read_text())
    for s in sources["sources"]:
        s["licence"] = "CHANGED LATER"
    (cfg / "sources.json").write_text(json.dumps(sources))
    d2, reused2 = build.build_site(data, cfg, prof, run_id)
    assert reused2 and d2 == d1 and (d2 / "about.html").read_text() == about1
    assert "CHANGED LATER" not in about1
    assert build.latest_run_id(data) == run_id


def test_publish_refuses_unvalidated_then_override(run_env, tmp_path):
    data, prof, cfg, run_id, rdir = run_env
    public = tmp_path / "public"
    public.mkdir()
    (public / "old.txt").write_text("previous site")
    code = build.publish(data, cfg, prof, run_id, public)
    assert code == errors.PUBLISH_REFUSED and (public / "old.txt").is_file()  # unchanged
    (rdir / "calibration.json").write_text(
        json.dumps({"flag_for_review": True, "flag_reasons": ["no_known_analog_in_top_20pct"]})
    )
    assert build.publish(data, cfg, prof, run_id, public) == errors.PUBLISH_REFUSED
    assert build.publish(data, cfg, prof, run_id, public, allow_unvalidated=True) == errors.OK
    assert not (public / "old.txt").exists() and (public / ".nojekyll").is_file()
    for f in html_files(public):
        assert "no_known_analog_in_top_20pct" in f.read_text(), f
    assert not list(tmp_path.glob("public.tmp-*")) and not list(tmp_path.glob("public.old-*"))


def test_publish_refuses_preview(run_env, tmp_path):
    data, prof, cfg, run_id, rdir = run_env
    res = json.loads(json.dumps(SAMPLE))
    res["run_record"]["refinement"]["stop"] = "skipped"
    (rdir / "results.json").write_text(json.dumps(res))
    code = build.publish(data, cfg, prof, run_id, tmp_path / "pub", allow_unvalidated=True)
    assert code == errors.PUBLISH_REFUSED and not (tmp_path / "pub").exists()


def test_cli_site_and_publish(run_env, tmp_path, capsys):
    data, prof, cfg, run_id, _ = run_env
    base = ["--data-dir", str(data), "--config-dir", str(cfg)]
    assert cli.main(base + ["site", "--latest", "--profiles-dir", str(prof)]) == errors.OK
    assert "site of run" in capsys.readouterr().out
    pub = tmp_path / "pub"
    args = ["publish", "--run", run_id, "--profiles-dir", str(prof), "--public-dir", str(pub)]
    assert cli.main(base + args) == errors.PUBLISH_REFUSED
    assert cli.main(base + args + ["--allow-unvalidated"]) == errors.OK
    assert (pub / "index.html").is_file()
