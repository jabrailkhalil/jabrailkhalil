from __future__ import annotations

import json
import math
import os
import urllib.request
from pathlib import Path

TOKEN = os.environ["GITHUB_TOKEN"]
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "jabrailkhalil-profile-reach-metrics",
}


def repo_meta(repo: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


metrics_path = Path("metrics/upstream-downloads.json")
section_path = Path("metrics/upstream-section.md")
readme_path = Path("README.md")

metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
reach: dict[str, dict] = {}

for repo, data in metrics["repositories"].items():
    if data.get("public_downloads") is not None:
        continue
    meta = repo_meta(repo)
    stars = int(meta.get("stargazers_count", 0))
    forks = int(meta.get("forks_count", 0))
    estimate = math.floor(stars + 0.5 * forks + 0.5)
    if estimate == 0 and (stars > 0 or forks > 0):
        estimate = 1
    reach[repo] = {
        "estimated_users": estimate,
        "stars": stars,
        "forks": forks,
        "method": "stars + 0.5 * forks",
    }

metrics["source_only_reach_estimates"] = reach
metrics.setdefault("notes", []).append(
    "For source-only repositories without a public cumulative download counter, README reach is estimated as stars + 0.5 * forks; these user estimates are not added to the download total."
)
metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")

lines = section_path.read_text(encoding="utf-8").splitlines()
patched: list[str] = []
for line in lines:
    if line == "| Project | Stars | Downloads | Merged PR |":
        line = "| Project | Stars | Usage / reach | Merged PR |"
    for repo, info in reach.items():
        needle = f"](https://github.com/{repo})"
        if line.startswith("| [") and needle in line and " | — | " in line:
            unit = "user" if info["estimated_users"] == 1 else "users"
            line = line.replace(
                " | — | ",
                f" | ≈{human(info['estimated_users'])} {unit} | ",
                1,
            )
            break
    if line.startswith("> Sources:"):
        line = (
            "> Sources: [npm](https://www.npmjs.com/), [PyPI / Pepy](https://www.pepy.tech/), "
            "[crates.io](https://crates.io/), [Docker Hub](https://hub.docker.com/), "
            "[GitHub Releases](https://github.com/), [RubyGems](https://rubygems.org/), "
            "[Packagist](https://packagist.org/) and [NuGet](https://www.nuget.org/). "
            "Download values are cumulative public download events and may overlap across channels. "
            "For source-only projects without a public cumulative download counter, `users` is an estimated public GitHub reach using `stars + 0.5 × forks` "
            "(the midpoint of the observable unique-account range from `stars` to `stars + forks`). "
            "User estimates are **not** included in the public download total. "
            "[Per-source breakdown](https://github.com/jabrailkhalil/jabrailkhalil/blob/main/metrics/upstream-downloads.json)."
        )
    patched.append(line)

section = "\n".join(patched).rstrip() + "\n"
section_path.write_text(section, encoding="utf-8")

readme = readme_path.read_text(encoding="utf-8")
start = readme.index("## 🛰️ Upstream open-source")
end = readme.index("## 🧰 Core stack")
readme_path.write_text(readme[:start] + section.rstrip() + "\n\n" + readme[end:], encoding="utf-8")
