#!/usr/bin/env python3
"""Turn specs/<feature>/tasks.md into GitHub issues, sub-issues and project items.

Structure created:
  * one parent issue per tasks.md phase (Setup, Foundational, US1..US5, Polish)
  * one sub-issue per task (title "T051: ..."), linked to its phase parent
  * labels: speckit, story:USn, area:<team area>, parallel
  * milestones: MVP (Setup+Foundational+US1), US2 Site, US3 Profiles, US4 Calibration,
    US5 Dedup, Polish
  * every issue added to an existing Projects (v2) board with fields
    Status=Todo, Priority, Phase, Area

Re-runnable: existing issues are found by title prefix ("T051:" / "Phase 3:") and are
updated instead of duplicated. tasks.md stays the source of truth.

Default is a dry run (prints the plan, writes nothing to GitHub). Use --apply to create.
Requires the GitHub CLI (`gh`) logged in with scopes repo + project.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path

ID = r"T\d{3}"
DASH = "–"  # en dash used in ranges like T037–T042

PHASE_KEYS = {  # phase number -> (key, milestone, priority)
    1: ("Setup", "MVP", "P0"),
    2: ("Foundational", "MVP", "P0"),
    3: ("US1", "MVP", "P0"),
    4: ("US2", "US2 Site", "P1"),
    5: ("US3", "US3 Profiles", "P1"),
    6: ("US4", "US4 Calibration", "P2"),
    7: ("US5", "US5 Dedup", "P2"),
    8: ("Polish", "Polish", "P2"),
}
MILESTONES = {
    "MVP": "Setup + Foundational + User Story 1: ranked, explained results from one command.",
    "US2 Site": "User Story 2: lightweight static results site.",
    "US3 Profiles": "User Story 3: profile validation, freezing, extraction, second profile by config.",
    "US4 Calibration": "User Story 4: calibration against known analogs and weight stability.",
    "US5 Dedup": "User Story 5 (later stage): known analog / new candidate labels.",
    "Polish": "Cross-cutting: cleanup, README, verification, quickstart validation, review.",
}
AREAS = {"A": "earth-data", "B": "planetary-scoring", "C": "app-site"}
LABELS = {
    "speckit": ("5319e7", "Generated from Spec Kit tasks.md"),
    "parallel": ("bfd4f2", "Can run in parallel with other [P] tasks"),
    "story:US1": ("0e8a16", "User Story 1 - run analysis (P1, MVP)"),
    "story:US2": ("1d76db", "User Story 2 - results site (P2)"),
    "story:US3": ("fbca04", "User Story 3 - profiles (P3)"),
    "story:US4": ("d93f0b", "User Story 4 - calibration (P4)"),
    "story:US5": ("c5def5", "User Story 5 - deduplication (P5, later)"),
    "area:earth-data": ("006b75", "Team area: Earth data"),
    "area:planetary-scoring": ("8a2be2", "Team area: planetary data + scoring"),
    "area:app-site": ("b60205", "Team area: app + site"),
}


# --------------------------------------------------------------------------- parsing

def expand_ids(text: str) -> list[str]:
    """Expand 'T037–T042, T045' style references into a list of ids."""
    out: list[str] = []
    for a, b in re.findall(rf"({ID})(?:\s*[{DASH}-]\s*({ID}))?", text):
        if b:
            out += [f"T{n:03d}" for n in range(int(a[1:]), int(b[1:]) + 1)]
        else:
            out.append(a)
    return out


def parse_tasks(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    phases: list[dict] = []
    tasks: dict[str, dict] = {}
    deps: dict[str, set[str]] = {}
    area_of: dict[str, str] = {}
    section = None
    for line in lines:
        m = re.match(r"^## Phase (\d+): (.+)$", line)
        if m:
            num = int(m.group(1))
            phases.append({"num": num, "title": m.group(2).strip(), "info": [], "tasks": []})
            section = "phase"
            continue
        if line.startswith("### Key task dependencies"):
            section = "deps"
            continue
        if line.startswith("### Suggested team split"):
            section = "team"
            continue
        if line.startswith("## ") or (line.startswith("### ") and section in ("deps", "team")):
            section = None
            continue
        if section == "phase" and phases:
            t = re.match(rf"^- \[ \] ({ID})( \[P\])?( \[(US\d)\])? (.+)$", line)
            if t:
                tid, par, story, desc = t.group(1), bool(t.group(2)), t.group(4), t.group(5)
                tasks[tid] = {"id": tid, "parallel": par, "story": story, "desc": desc,
                              "phase": phases[-1]["num"]}
                phases[-1]["tasks"].append(tid)
                continue
            i = re.match(r"^\*\*(Goal|Purpose|Independent Test|Checkpoint)\*\*: (.+)$", line)
            if i:
                phases[-1]["info"].append((i.group(1), i.group(2)))
        elif section == "deps" and line.startswith("- "):
            for chain in line[2:].split(";"):
                segs = [expand_ids(seg) for seg in chain.split("→")]  # →
                for left, right in pairwise(segs):
                    for r in right:
                        deps.setdefault(r, set()).update(left)
        elif section == "team":
            p = re.match(r"^- \*\*Person ([ABC]) .*?\*\*: (.+)$", line)
            if p:
                for tid in expand_ids(p.group(2)):
                    area_of[tid] = AREAS[p.group(1)]
    for tid, d in deps.items():
        d.discard(tid)
    return {"phases": phases, "tasks": tasks, "deps": deps, "area": area_of}


def short_title(tid: str, desc: str, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", desc)
    cut, tick = text, False
    for k, ch in enumerate(text):  # first ": ", "; " or " (" outside `code`
        if ch == "`":
            tick = not tick
        elif not tick and (text[k:k + 2] in (": ", "; ") or text[k:k + 2] == " ("):
            cut = text[:k]
            break
    cut = cut.rstrip(" .")
    if len(cut) > limit:
        cut = cut[: limit - 1].rsplit(" ", 1)[0] + "…"
    return f"{tid}: {cut}"


def split_done(desc: str) -> tuple[str, list[str]]:
    m = re.search(r"\bDone: (.+)$", desc)
    if not m:
        return desc, []
    body = desc[: m.start()].rstrip()
    checks = [c.strip().rstrip(".") for c in re.split(r";\s+", m.group(1)) if c.strip()]
    return body, checks


# --------------------------------------------------------------------------- gh helpers

class GH:
    def __init__(self, repo: str, apply: bool, delay: float):
        self.repo, self.apply, self.delay = repo, apply, delay
        self.calls = 0

    def run(self, args: list[str], mutate: bool = False, stdin: str | None = None) -> str:
        if mutate and not self.apply:
            return ""
        if mutate:
            time.sleep(self.delay)
            self.calls += 1
        res = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])}… failed: {res.stderr.strip()}")
        return res.stdout

    def api(self, method: str, path: str, fields: dict | None = None, mutate: bool = True) -> dict:
        args = ["api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
        stdin = None
        if fields is not None:
            args += ["--input", "-"]
            stdin = json.dumps(fields)
        out = self.run(args, mutate=mutate, stdin=stdin)
        return json.loads(out) if out.strip() else {}


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="MarkianCloudian/NasaSpaceAppsChallenge")
    ap.add_argument("--branch", default="dev-app-v1", help="branch used for links to spec files")
    ap.add_argument("--feature", default="specs/001-earth-analog-finder")
    ap.add_argument("--project-owner", default="MarkianCloudian")
    ap.add_argument("--project-number", type=int, default=1)
    ap.add_argument("--apply", action="store_true", help="actually create/update on GitHub")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between write calls")
    ap.add_argument("--plan-out", help="write the full planned issue bodies to this file")
    a = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    data = parse_tasks(root / a.feature / "tasks.md")
    phases, tasks, deps, area_of = data["phases"], data["tasks"], data["deps"], data["area"]
    blob = f"https://github.com/{a.repo}/blob/{a.branch}/{a.feature}"
    gh = GH(a.repo, a.apply, a.delay)

    # ---- existing state (read-only calls)
    existing = json.loads(gh.run(["issue", "list", "-R", a.repo, "--state", "all", "--limit", "1000",
                                  "--json", "number,title,id,url"]))
    by_key = {}
    for it in existing:
        m = re.match(rf"^({ID}|Phase \d+):", it["title"])
        if m:
            by_key[m.group(1)] = it
    labels_have = {l["name"] for l in json.loads(gh.run(["label", "list", "-R", a.repo, "--limit", "200", "--json", "name"]))}
    ms_have = {m["title"]: m["number"] for m in json.loads(gh.run(["api", f"repos/{a.repo}/milestones?state=all&per_page=100"]))}
    proj = json.loads(gh.run(["project", "view", str(a.project_number), "--owner", a.project_owner, "--format", "json"]))
    fields = {f["name"]: f for f in json.loads(gh.run(["project", "field-list", str(a.project_number), "--owner",
                                                       a.project_owner, "--format", "json"]))["fields"]}

    # ---- plan
    phase_title = {p["num"]: f"Phase {p['num']}: {p['title']}" for p in phases}
    plan_issues = []
    for p in phases:
        key, ms, prio = PHASE_KEYS[p["num"]]
        info = "\n".join(f"**{k}**: {v}" for k, v in p["info"])
        body = (f"{info}\n\n**Tasks**: {', '.join(p['tasks'])} (sub-issues below).\n\n"
                f"Source: [tasks.md]({blob}/tasks.md) · [plan.md]({blob}/plan.md) · [spec.md]({blob}/spec.md)\n\n"
                f"_Generated from Spec Kit `tasks.md`; edit there and re-run `scripts/tasks_to_issues.py`._")
        plan_issues.append({"key": f"Phase {p['num']}", "title": phase_title[p["num"]], "body": body,
                            "labels": ["speckit"] + ([f"story:{key}"] if key.startswith("US") else []),
                            "milestone": ms, "parent": None, "phase": key, "priority": prio, "area": None,
                            "deps": []})
    for tid in sorted(tasks):
        t = tasks[tid]
        key, ms, prio = PHASE_KEYS[t["phase"]]
        work, checks = split_done(t["desc"])
        refs = sorted(set(re.findall(r"plan ([A-I]\d)", t["desc"])))
        d = sorted(deps.get(tid, set()))
        labels = ["speckit"] + ([f"story:{t['story']}"] if t["story"] else [])
        labels += ([f"area:{area_of[tid]}"] if tid in area_of else []) + (["parallel"] if t["parallel"] else [])
        plan_issues.append({"key": tid, "title": short_title(tid, t["desc"]), "work": work, "checks": checks,
                            "labels": labels, "milestone": ms, "parent": f"Phase {t['phase']}", "phase": key,
                            "priority": prio, "area": area_of.get(tid), "deps": d, "plan_refs": refs,
                            "parallel": t["parallel"]})

    F = a.feature

    def read_first(it: dict) -> list[str]:
        text = it["work"] + " " + " ".join(it["checks"])
        items = ["`CLAUDE.md` → *Working on a task*", "`.specify/memory/constitution.md`",
                 f"`{F}/tasks.md` → **{it['key']}**"]
        if it["plan_refs"]:
            items.append(f"`{F}/plan.md` → sub-phase {', '.join(it['plan_refs'])}")
        decisions = sorted(set(re.findall(r"D-\d{3}", text)))
        if decisions:
            items.append(f"`{F}/research.md` → {', '.join(decisions)}")
        contracts = set(re.findall(r"contracts/([\w.-]+\.(?:md|json))", text))
        contracts |= {f"{n}.schema.json" for n in re.findall(r"schemas/([\w-]+)\.schema\.json", text)}
        if "src/analogfinder" in text or "tests/" in text:
            contracts.add("internal-api.md")
        for c in sorted(contracts):
            items.append(f"`{F}/contracts/{c}`")
        if "data-model" in text or "data model" in text:
            items.append(f"`{F}/data-model.md`")
        return items

    def task_body(it: dict, numbers: dict) -> str:
        dep_txt = ", ".join(f"#{numbers[x]} ({x})" if x in numbers else x for x in it["deps"]) or "—"
        checks = "\n".join(f"- [ ] {c}" for c in it["checks"]) or "- [ ] See task description"
        rf = "\n".join(f"- {r}" for r in read_first(it))
        return (f"**Spec Kit task {it['key']}** · phase {it['phase']} · "
                f"{'parallel [P]' if it['parallel'] else 'sequential'}"
                f"{' · plan ' + ', '.join(it['plan_refs']) if it['plan_refs'] else ''}\n\n"
                f"### Work\n{it['work']}\n\n### Done when\n{checks}\n"
                f"- [ ] `uv run ruff check .` and `uv run pytest` pass\n\n"
                f"**Depends on**: {dep_txt} — these must be closed before starting.\n\n"
                f"### Read first (paths in branch `{a.branch}`)\n{rf}\n\n"
                f"### Rules\nOne branch `task/{it['key']}-…` off `{a.branch}`, one PR into `{a.branch}` with "
                f"`Closes #<this issue>`. Implement only this task; use `contracts/internal-api.md` and the "
                f"schemas as written; never invent data values or URLs (items marked *verify* must be checked "
                f"and recorded in `research.md`); do not tick `tasks.md`; ask here if anything is unclear.\n\n"
                # NOTE: never write the literal trigger word (at-sign + claude) into issue bodies:
                # the repo workflow starts a Claude run for every new issue whose body contains it.
                f"### Delegate to Claude\nPost a comment that starts with the Claude trigger (the at-sign "
                f"followed by `claude`), then: `implement this issue following CLAUDE.md and the \"Read "
                f"first\" list; open a PR into {a.branch}.` Ready-to-copy text: `CLAUDE.md` → "
                f"*Delegating a task*.\n\n"
                f"Links: [tasks.md]({blob}/tasks.md) · [plan.md]({blob}/plan.md) · "
                f"[research.md]({blob}/research.md) · [CLAUDE.md](https://github.com/{a.repo}/blob/{a.branch}/CLAUDE.md)\n\n"
                f"_Generated from Spec Kit `tasks.md`; edit there and re-run `scripts/tasks_to_issues.py`._")

    # ---- safety: issue bodies/titles must not contain the workflow trigger word
    trigger = "@" + "claude"
    for i in plan_issues:
        text = i["title"] + (i["body"] if "body" in i else task_body(i, {}))
        if trigger in text.lower():
            raise SystemExit(f"refusing: {i['key']} contains the Claude trigger word")

    # ---- dry-run report
    new = [i for i in plan_issues if i["key"] not in by_key]
    print(f"Repo {a.repo} · board '{proj['title']}' ({proj['url']})")
    print(f"Issues planned: {len(plan_issues)} ({len(phases)} phase parents + {len(tasks)} tasks); "
          f"new {len(new)}, existing to update {len(plan_issues) - len(new)}")
    print(f"Labels to create: {sorted(set(LABELS) - labels_have) or 'none'}")
    print(f"Milestones to create: {sorted(set(MILESTONES) - set(ms_have)) or 'none'}")
    new_fields = [n for n in ("Phase", "Area") if n not in fields]
    print(f"Project fields to create: {new_fields or 'none'}; reused: Status, Priority")
    no_area = [i["key"] for i in plan_issues if i["key"].startswith("T") and not i["area"]]
    print(f"Tasks without team area: {no_area or 'none'}")
    print()
    for i in plan_issues:
        extra = f" deps={','.join(i['deps'])}" if i["deps"] else ""
        print(f"[{i['phase']:<12}] {i['title'][:100]:<100} | ms={i['milestone']} prio={i['priority']} "
              f"labels={','.join(i['labels'])}{extra}")
    if a.plan_out:
        with open(a.plan_out, "w", encoding="utf-8") as fh:
            for i in plan_issues:
                body = i["body"] if "body" in i else task_body(i, {})
                fh.write(f"=== {i['title']}\nparent: {i['parent']} | milestone: {i['milestone']} | "
                         f"labels: {i['labels']}\n\n{body}\n\n")
        print(f"\nFull bodies written to {a.plan_out}")
    if not a.apply:
        print("\nDry run only. Re-run with --apply to create/update on GitHub.")
        return 0

    # ---- apply
    for name in sorted(set(LABELS) - labels_have):
        color, desc = LABELS[name]
        gh.run(["label", "create", name, "-R", a.repo, "--color", color, "--description", desc], mutate=True)
    for title in sorted(set(MILESTONES) - set(ms_have)):
        ms = gh.api("POST", f"repos/{a.repo}/milestones", {"title": title, "description": MILESTONES[title]})
        ms_have[title] = ms["number"]
    for name, opts in (("Phase", [PHASE_KEYS[k][0] for k in sorted(PHASE_KEYS)]), ("Area", list(AREAS.values()))):
        if name not in fields:
            gh.run(["project", "field-create", str(a.project_number), "--owner", a.project_owner, "--name", name,
                    "--data-type", "SINGLE_SELECT", "--single-select-options", ",".join(opts)], mutate=True)
    fields = {f["name"]: f for f in json.loads(gh.run(["project", "field-list", str(a.project_number), "--owner",
                                                       a.project_owner, "--format", "json"]))["fields"]}

    def opt(field: str, value: str | None) -> str | None:
        if value is None:
            return None
        for o in fields[field].get("options", []):
            if o["name"] == value:
                return o["id"]
        return None

    item_query = ("query($id: ID!) { node(id: $id) { ... on Issue { projectItems(first: 50) "
                  "{ nodes { id project { id } } } } } }")

    def project_item(url: str, node_id: str) -> dict:
        """Add the issue to the board, or return its existing item (boards may auto-add issues)."""
        try:
            return json.loads(gh.run(["project", "item-add", str(a.project_number), "--owner", a.project_owner,
                                      "--url", url, "--format", "json"], mutate=True))
        except RuntimeError as e:
            if "already exists" not in str(e):
                raise
        out = json.loads(gh.run(["api", "graphql", "-f", f"query={item_query}", "-f", f"id={node_id}"]))
        for node in out["data"]["node"]["projectItems"]["nodes"]:
            if node["project"]["id"] == proj["id"]:
                return {"id": node["id"]}
        raise RuntimeError(f"project item for {url} not found")

    numbers = {k: v["number"] for k, v in by_key.items()}
    node_ids = {k: v["id"] for k, v in by_key.items()}
    for i in plan_issues:
        body = i["body"] if "body" in i else task_body(i, numbers)
        payload = {"title": i["title"], "body": body, "labels": i["labels"], "milestone": ms_have[i["milestone"]]}
        if i["key"] in numbers:
            res = gh.api("PATCH", f"repos/{a.repo}/issues/{numbers[i['key']]}", payload)
            print(f"updated #{numbers[i['key']]} {i['key']}")
        else:
            res = gh.api("POST", f"repos/{a.repo}/issues", payload)
            numbers[i["key"]] = res["number"]
            print(f"created #{res['number']} {i['key']}")
        i["db_id"], i["url"] = res["id"], res["html_url"]
        node_ids[i["key"]] = res["node_id"]
        # sub-issue link
        if i["parent"]:
            try:
                gh.api("POST", f"repos/{a.repo}/issues/{numbers[i['parent']]}/sub_issues", {"sub_issue_id": res["id"]})
            except RuntimeError as e:
                if "already" not in str(e).lower() and "duplicate" not in str(e).lower():
                    print(f"  sub-issue link warning: {e}")
        # project item + fields
        item = project_item(i["url"], node_ids[i["key"]])
        for field, value in (("Status", "Todo"), ("Priority", i["priority"]), ("Phase", i["phase"]), ("Area", i["area"])):
            oid = opt(field, value)
            if oid:
                gh.run(["project", "item-edit", "--id", item["id"], "--project-id", proj["id"],
                        "--field-id", fields[field]["id"], "--single-select-option-id", oid], mutate=True)
    # second pass only for task bodies whose dependencies were created later than the task
    late = [i for i in plan_issues if "body" not in i and any(int(d[1:]) > int(i["key"][1:]) for d in i["deps"])]
    for i in late:
        gh.api("PATCH", f"repos/{a.repo}/issues/{numbers[i['key']]}", {"body": task_body(i, numbers)})
    print(f"\nDone: {gh.calls} write calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
