"""Refresh verified profile metrics. Run from the repository root.

Use --from-snapshot metrics/upstream.json to render without network access.
Closed PRs count as accepted imports only when curated commit evidence exists.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from html import escape
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

USER = "jabrailkhalil"
QUERY = f"is:pr author:{USER} is:merged -user:{USER}"
SEARCH_URL = "https://github.com/pulls?q=" + quote(QUERY, safe="")
IMPORTS = [
    {"repository": "google/adk-python", "number": 7406,
     "commit": "51a20e24918c8d4b2b05909f408fc1c79f80020a",
     "description": "SQLite in-memory session retention"},
    {"repository": "pytorch/pytorch", "number": 196518,
     "commit": "11cc3f2c2feafe59bf1d7f19c46edaa02b3eac25",
     "description": "CPython 3.13 list-comprehension tests for Dynamo"},
]


def github(path):
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "jabrailkhalil-profile-metrics"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request("https://api.github.com/" + path, headers=headers),
                 timeout=30) as response:
        return json.load(response)


def collect():
    prs = {}
    page = 1
    while True:
        data = github("search/issues?q=" + quote(QUERY, safe="")
                      + f"&sort=created&order=asc&per_page=100&page={page}")
        if data["incomplete_results"] or data["total_count"] > 1000:
            raise RuntimeError("Incomplete GitHub search; retaining previous snapshot")
        for pr in data["items"]:
            prs[pr["html_url"]] = {
                "repository": pr["repository_url"].split("/repos/", 1)[1],
                "number": pr["number"], "title": pr["title"],
                "url": pr["html_url"], "merged_at": pr["pull_request"]["merged_at"],
            }
        if len(prs) == data["total_count"]:
            break
        if not data["items"] or page >= 10:
            raise RuntimeError("GitHub pagination ended before all results were collected")
        page += 1
    repositories = []
    for name in sorted({pr["repository"] for pr in prs.values()}):
        repo = github("repos/" + name)
        repositories.append({"name": repo["full_name"], "url": repo["html_url"],
                             "stars": repo["stargazers_count"]})
    for item in IMPORTS:
        commit = github(f"repos/{item['repository']}/commits/{item['commit']}")
        if commit["sha"] != item["commit"] or str(item["number"]) not in commit["commit"]["message"]:
            raise RuntimeError("Import evidence does not match the curated PR")
    return {"schema_version": 1,
            "verified_on": datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat(),
            "username": USER, "query": QUERY,
            "pull_requests": sorted(prs.values(), key=lambda p: p["url"]),
            "repositories": repositories}


def validate(data):
    prs, repos = data["pull_requests"], data["repositories"]
    names = {repo["name"] for repo in repos}
    if not prs or len({p["url"] for p in prs}) != len(prs):
        raise ValueError("Empty or duplicate merge snapshot")
    if len(names) != len(repos) or names != {p["repository"] for p in prs}:
        raise ValueError("Repository snapshot does not match the merged PRs")
    for pr in prs:
        if not pr["merged_at"] or pr["repository"].split("/")[0].lower() == USER:
            raise ValueError("Snapshot includes an unmerged or own-repository PR")
    if data["username"] != USER or data["query"] != QUERY:
        raise ValueError("Unexpected snapshot scope")
    datetime.fromisoformat(data["verified_on"])


def human(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def text(x, y, value, kind="label"):
    return f'<text x="{x}" y="{y}" class="{kind}">{escape(str(value))}</text>'


def bar(x, y, width):
    return f'<rect x="{x}" y="{y}" width="{width:.1f}" height="18" rx="6" fill="url(#accent)"/>'


def svg(title, description, subtitle, body, date, height):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#0d1117"/><stop offset="1" stop-color="#1e1b4b"/></linearGradient>
<linearGradient id="accent"><stop stop-color="#22d3ee"/><stop offset="1" stop-color="#818cf8"/></linearGradient></defs>
<style>text{{font-family:Inter,"Segoe UI",sans-serif}}.title{{fill:#f8fafc;font-size:27px;font-weight:700}}.subtitle{{fill:#a5b4c9;font-size:14px}}.label{{fill:#e2e8f0;font-size:15px}}.value{{fill:#f8fafc;font-size:17px;font-weight:700}}.muted{{fill:#94a3b8;font-size:12px}}</style>
<rect x="1" y="1" width="998" height="{height-2}" rx="20" fill="url(#bg)" stroke="#30363d"/>
{text(38, 49, title, "title")}{text(38, 77, subtitle, "subtitle")}
{body}
{text(38, height-20, 'Verified ' + date + ' · GitHub-recorded merges in external repositories', 'muted')}
</svg>
'''


def charts(data):
    prs, repos = data["pull_requests"], data["repositories"]
    date = data["verified_on"]
    count, projects = len(prs), len(repos)
    top = sorted(repos, key=lambda r: (-r["stars"], r["name"]))[:10]
    body = text(38, 112, "Top 10 repositories by stars · logarithmic scale · stars are not user counts", "muted")
    for i, repo in enumerate(top):
        y = 151 + i * 37
        body += text(38, y, repo["name"].split("/")[-1])
        width = 530 * math.log1p(repo["stars"]) / max(1, math.log1p(top[0]["stars"]))
        body += bar(240, y-15, width) + text(790, y, human(repo["stars"]) + " ★", "value")
    result = {"upstream-impact.svg": svg("Upstream contributions",
        f"{count} merges in {projects} projects; top ten repositories by stars.",
        f"{count} merged PRs · {projects} upstream projects", body, date, 555)}

    counts = Counter(pr["repository"] for pr in prs)
    leaders = sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:6]
    rows = [(name.split("/")[-1], n) for name, n in leaders]
    rows.append((f"Other {projects-len(leaders)} projects", count-sum(n for _, n in leaders)))
    body = ""
    for i, (name, n) in enumerate(rows):
        y = 129 + i * 41
        body += text(38, y, name) + bar(260, y-15, 580*n/max(n for _, n in rows))
        body += text(875, y, n, "value")
    result["contribution-spectrum.svg"] = svg("Where I contribute",
        "Merged PR counts by repository, with the remaining projects grouped together.",
        f"All {count} merged PRs, grouped by upstream repository", body, date, 435)

    buckets = [("50k+ stars", 50000, float("inf")), ("10k–50k stars", 10000, 50000),
               ("1k–10k stars", 1000, 10000), ("Under 1k stars", 0, 1000)]
    body = ""
    for i, (label, low, high) in enumerate(buckets):
        n = sum(low <= r["stars"] < high for r in repos)
        y = 132 + i * 48
        body += text(38, y, label) + bar(240, y-15, 580*n/projects)
        body += text(855, y, f"{n} projects", "value")
    body += text(38, 339, "Repository popularity provides context; it does not measure adoption of my changes.", "muted")
    result["project-scale.svg"] = svg("Projects of different sizes",
        f"Star-count distribution of {projects} upstream repositories.",
        f"{projects} repositories · each project counted once", body, date, 390)

    months = Counter(pr["merged_at"][:7] for pr in prs)
    body = ""
    for i, (month, n) in enumerate(sorted(months.items())):
        y = 130 + i * 44
        body += text(38, y, month) + bar(200, y-15, 630*n/max(months.values()))
        body += text(865, y, n, "value")
    result["merged-pr-momentum.svg"] = svg("Merged contributions over time",
        "GitHub-recorded upstream PR merges by calendar month (UTC).",
        "Monthly merge counts · current month is partial · UTC timestamps",
        body, date, 185+44*len(months))
    return result


def section(data):
    prs, repos = data["pull_requests"], data["repositories"]
    merged_keys = {(p["repository"].lower(), p["number"]) for p in prs}
    imports = [i for i in IMPORTS if (i["repository"].lower(), i["number"]) not in merged_keys]
    all_projects = {r["name"].lower() for r in repos} | {i["repository"].lower() for i in imports}
    date = datetime.fromisoformat(data["verified_on"]).strftime("%d %B %Y").lstrip("0")
    lines = [f"**{len(prs)} merged PRs across {len(repos)} upstream projects**, verified on **{date}**.", "",
        f"[![Merged upstream PRs](https://img.shields.io/badge/merged_upstream_PRs-{len(prs)}-2EA44F?style=flat-square&logo=github)]({SEARCH_URL})",
        f"[![Upstream projects](https://img.shields.io/badge/upstream_projects-{len(repos)}-0EA5E9?style=flat-square)]({SEARCH_URL})", "",
        f"Including **{len(imports)} contributions accepted through upstream imports**, the total is **{len(prs)+len(imports)} accepted contributions across {len(all_projects)} projects**. GitHub records those imported PRs as closed without a merge timestamp, so they are listed separately:", ""]
    for item in imports:
        repo, n = item["repository"], item["number"]
        lines.append(f"- [{repo} #{n}](https://github.com/{repo}/pull/{n}) — {item['description']}; [accepted commit](https://github.com/{repo}/commit/{item['commit']}).")
    lines += ["", "These counts describe accepted upstream work; release inclusion and downstream adoption are separate questions.", "",
        "<details>", f"<summary><strong>All {len(repos)} projects and {len(prs)} merged PRs</strong></summary>", "",
        "| Project | Stars | Merged PRs |", "| --- | ---: | --- |"]
    for repo in sorted(repos, key=lambda r: (-r["stars"], r["name"])):
        matches = sorted((p for p in prs if p["repository"].lower() == repo["name"].lower()), key=lambda p: p["number"])
        links = ", ".join(f"[#{p['number']}]({p['url']})" for p in matches)
        lines.append(f"| [{repo['name']}]({repo['url']}) | {human(repo['stars'])} ⭐ | {links} |")
    lines += ["", "Stars are a dated GitHub snapshot. Own repositories and open or unmerged PRs are excluded.", "", "</details>", "",
        f'<a href="{SEARCH_URL}"><img width="100%" alt="{len(prs)} merged PRs across {len(repos)} upstream projects and repository star context" src="./assets/upstream-impact.svg" /></a>', "",
        "<details>", "<summary><strong>Contribution breakdown and history</strong></summary>", "",
        "![Merged PRs by upstream repository](./assets/contribution-spectrum.svg)", "",
        "![Distribution of upstream repository sizes](./assets/project-scale.svg)", "",
        "![Monthly upstream merge counts](./assets/merged-pr-momentum.svg)", "", "</details>", "",
        "[Live merged-PR query](" + SEARCH_URL + ") · [Verified snapshot](./metrics/upstream.json) · Counts, table and charts refresh together weekly."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-snapshot", type=Path)
    args = parser.parse_args()
    data = json.loads(args.from_snapshot.read_text(encoding="utf-8")) if args.from_snapshot else collect()
    validate(data)
    generated = section(data)
    assets = charts(data)
    readme_path = Path("README.md")
    readme = readme_path.read_text(encoding="utf-8")
    start, end = "<!-- UPSTREAM:START -->", "<!-- UPSTREAM:END -->"
    if readme.count(start) != 1 or readme.count(end) != 1:
        raise ValueError("Expected exactly one upstream marker pair")
    before, rest = readme.split(start, 1)
    _, after = rest.split(end, 1)
    # Complete collection and validation before changing tracked files.
    Path("metrics").mkdir(exist_ok=True)
    Path("assets").mkdir(exist_ok=True)
    Path("metrics/upstream.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path("metrics/upstream-section.md").write_text(generated, encoding="utf-8")
    for name, content in assets.items():
        Path("assets", name).write_text(content, encoding="utf-8")
    readme_path.write_text(before + start + "\n" + generated + end + after, encoding="utf-8")
    print(f"Verified {len(data['pull_requests'])} merged PRs in {len(data['repositories'])} upstream projects")


if __name__ == "__main__":
    main()
