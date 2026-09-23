"""Refresh the profile using public, merged pull requests to other owners."""

import html
import json
import os
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


def render(items, login):
    groups = {}
    for item in sorted(items, key=lambda p: (p["mergedAt"], p["url"]), reverse=True):
        groups.setdefault(item["repository"]["nameWithOwner"], []).append(item)
    lines = ["## Open-source contributions", "",
             f"**{len(items)} merged PRs · {len(groups)} projects**", ""]
    for name, prs in list(groups.items())[:5]:
        lines += [f"### [{name}](https://github.com/{name}) · {len(prs)} merged", ""]
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
    content = render(fetch_contributions(owner), owner)
    target = Path(__file__).resolve().parents[1] / "README.md"
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        target.write_text(content, encoding="utf-8")
        print("Updated README.md")
    else:
        print("Contributions unchanged")
