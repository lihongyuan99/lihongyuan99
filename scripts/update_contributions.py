"""Refresh the profile using public, merged pull requests to other owners."""

import base64
import html
import json
import os
import re
from pathlib import Path
import subprocess
from urllib.parse import urlencode

EXCLUDED_REPOSITORIES = {"hisn00w/asu-skills"}

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    pullRequests(first: 100, after: $cursor, states: MERGED,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo {hasNextPage endCursor}
      nodes {
        title url number mergedAt
        repository {nameWithOwner isPrivate owner {login}}
      }
    }
  }
}
"""


def fetch_contributions(login):
    items = {}
    cursor = None
    while True:
        command = ["gh", "api", "graphql", "-f", f"query={QUERY}",
                   "-f", f"login={login}"]
        if cursor:
            command += ["-f", f"cursor={cursor}"]
        response = json.loads(subprocess.check_output(command, text=True))
        if response.get("errors"):
            raise RuntimeError("GitHub returned an incomplete GraphQL response")
        page = response["data"]["user"]["pullRequests"]
        for item in page["nodes"]:
            repo = item["repository"]
            if (repo and not repo["isPrivate"] and item["mergedAt"]
                    and repo["owner"]["login"].lower() != login.lower()
                    and repo["nameWithOwner"].lower() not in EXCLUDED_REPOSITORIES):
                items[item["url"]] = item
        if not page["pageInfo"]["hasNextPage"]:
            return list(items.values())
        next_cursor = page["pageInfo"]["endCursor"]
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("GitHub pagination did not advance")
        cursor = next_cursor


def safe_title(title):
    # Entity escaping keeps external PR titles from becoming HTML or Markdown.
    return "".join(
        f"&#{ord(char)};" if char in "\\`*_{}[]()#!|~" else html.escape(char, quote=True)
        for char in " ".join(title.split())
    )



def fetch_badges(repositories):
    """Reuse only supported Trending badges actually present in upstream READMEs."""
    badges = {}
    for name in sorted(repositories):
        result = subprocess.run(
            ["gh", "api", f"repos/{name}/readme"], capture_output=True, text=True
        )
        if result.returncode:
            if "HTTP 404" in result.stderr:
                continue
            raise RuntimeError(f"Could not read upstream README: {name}")
        readme = base64.b64decode(json.loads(result.stdout)["content"]).decode("utf-8")
        match = re.search(
            r'https://trendshift\.io/api/badge/(?:trendshift/)?repositories/(\d+)(?:/daily)?',
            readme,
        )
        if match:
            badges[name] = (
                f'<a href="https://trendshift.io/repositories/{match.group(1)}">'
                f'<img src="{match.group(0)}" alt="{html.escape(name)} | Trendshift" '
                'width="136" height="30" align="center" /></a>'
            )
            continue
        match = re.search(
            r'https://img\.shields\.io/badge/GitHub%20Trending-[^\s)\"<>]+',
            readme, re.IGNORECASE,
        )
        if match:
            badges[name] = (
                f'<a href="https://github.com/trending"><img src="{html.escape(match.group(0), quote=True)}" '
                'alt="GitHub Trending" height="20" align="center" /></a>'
            )
    return badges


def render(items, login, badges=None):
    badges = badges or {}
    groups = {}
    for item in sorted(items, key=lambda p: (p["mergedAt"], p["url"]), reverse=True):
        groups.setdefault(item["repository"]["nameWithOwner"], []).append(item)
    lines = ["## Open-source contributions", "",
             f"**{len(items)} merged PRs · {len(groups)} projects**", ""]
    for name, prs in list(groups.items())[:5]:
        heading = f"### [{name}](https://github.com/{name}) · {len(prs)} merged"
        if name in badges:
            heading += f" &nbsp; {badges[name]}"
        lines += [heading, ""]
        for pr in prs[:3]:
            lines.append(f"- {safe_title(pr['title'])} — "
                         f"[#{pr['number']}]({pr['url']}) · {pr['mergedAt'][:10]}")
        lines.append("")
    query = f"author:{login} is:pr is:merged is:public -user:{login}"
    url = "https://github.com/search?" + urlencode({"q": query, "type": "pullrequests"})
    lines += ["---", "", "All contributions listed above have been merged.", "",
              f"[View all merged public PRs →]({url})", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    owner = os.environ.get("PROFILE_OWNER", "lihongyuan99")
    items = fetch_contributions(owner)
    badges = fetch_badges({item["repository"]["nameWithOwner"] for item in items})
    content = render(items, owner, badges)
    target = Path(__file__).resolve().parents[1] / "README.md"
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
        print("Updated README.md")
    else:
        print("Contributions unchanged")
