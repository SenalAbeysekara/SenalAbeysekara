import os
import json
import math
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta, timezone
from html import escape
from urllib.parse import quote

USER = os.getenv("GITHUB_USERNAME", "SenalAbeysekara")
TOKEN = os.getenv("GH_TOKEN") or os.getenv("METRICS_TOKEN")
OUT = "github-analytics.svg"

# Sri Lanka timezone offset
TIMEZONE_OFFSET = float(os.getenv("UTC_OFFSET", "5.5"))

if not TOKEN:
    raise SystemExit("Missing GH_TOKEN / METRICS_TOKEN secret")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "profile-analytics-svg",
}

LANG_COLORS = {
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "Java": "#b07219",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "PHP": "#4F5D95",
    "Blade": "#f7523f",
    "Dart": "#00B4AB",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Ruby": "#701516",
    "Vue": "#41b883",
    "Shell": "#89e051",
}

FALLBACK_COLORS = [
    "#2f81f7",
    "#d29922",
    "#3fb950",
    "#f85149",
    "#a371f7",
    "#39c5cf",
    "#ff7b72",
    "#db61a2",
]


def request_json(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = dict(HEADERS)

    if payload is not None:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API error {error.code}: {body}")


def safe_request_json(url, context="GitHub API request"):
    try:
        return request_json(url)
    except SystemExit as error:
        print(f"Skipped: {context}")
        print(error)
        return None


def graphql(query, variables):
    response = request_json(
        "https://api.github.com/graphql",
        "POST",
        {
            "query": query,
            "variables": variables,
        },
    )

    if response.get("errors"):
        raise SystemExit(json.dumps(response["errors"], indent=2))

    return response["data"]


def get_repos():
    repos = []
    page = 1

    while True:
        url = (
            "https://api.github.com/user/repos"
            "?visibility=all"
            "&affiliation=owner,collaborator,organization_member"
            f"&per_page=100&page={page}"
            "&sort=updated&direction=desc"
        )

        batch = request_json(url)

        if not batch:
            break

        repos.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    return repos


def print_repo_access_report(repos):
    public_repos = [repo for repo in repos if not repo.get("private")]
    private_repos = [repo for repo in repos if repo.get("private")]
    fork_repos = [repo for repo in repos if repo.get("fork")]

    print("Repo access check:")
    print(f"Accessible public repos: {len(public_repos)}")
    print(f"Accessible private repos: {len(private_repos)}")
    print(f"Accessible fork repos: {len(fork_repos)}")
    print(f"Total accessible repos: {len(repos)}")


def get_languages(repos):
    totals = {}

    for index, repo in enumerate(repos, start=1):
        if repo.get("fork"):
            continue

        context = "private repo languages" if repo.get("private") else f"{repo.get('full_name')} languages"
        languages = safe_request_json(repo["languages_url"], context=context)

        if not languages:
            continue

        for name, size in languages.items():
            totals[name] = totals.get(name, 0) + int(size)

    return sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]


def get_search_count(query):
    url = "https://api.github.com/search/issues?q=" + quote(query, safe=":")
    data = safe_request_json(url, context=f"search count for {query}")
    return int(data.get("total_count", 0)) if data else 0


def get_total_prs_from_search():
    # Matches GitHub search: type:pr author:SenalAbeysekara
    return get_search_count(f"type:pr author:{USER}")


def get_total_issues_from_search():
    # Real issues only, not PRs
    return get_search_count(f"type:issue author:{USER}")


def get_repo_branches(repo, repo_label):
    branches = []
    page = 1

    while True:
        url = (
            f"https://api.github.com/repos/{repo['full_name']}/branches"
            f"?per_page=100&page={page}"
        )

        batch = safe_request_json(url, context=f"{repo_label} branches page {page}")

        if not batch:
            break

        branches.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    return branches


def get_total_commits_from_repos(repos):
    """
    Counts actual commits authored by USER across accessible public/private repos.

    Important:
    - Checks all branches, including dev branches.
    - Deduplicates commits by SHA.
    - Shows private repo names in workflow logs temporarily for debugging.
    """
    seen_commits = set()

    total_public_repos_checked = 0
    total_private_repos_checked = 0
    total_branches_checked = 0

    for repo in repos:
        full_name = repo.get("full_name")
        if not full_name:
            continue

        is_private = repo.get("private", False)

        if is_private:
            total_private_repos_checked += 1
            repo_label = full_name
        else:
            total_public_repos_checked += 1
            repo_label = full_name

        branches = get_repo_branches(repo, repo_label)

        if not branches and repo.get("default_branch"):
            branches = [{"name": repo["default_branch"]}]

        print(f"Checking {repo_label}: {len(branches)} branches")

        repo_commit_count_before = len(seen_commits)

        for branch in branches:
            branch_name = branch.get("name")
            if not branch_name:
                continue

            total_branches_checked += 1
            page = 1

            while True:
                url = (
                    f"https://api.github.com/repos/{full_name}/commits"
                    f"?sha={quote(branch_name, safe='')}"
                    f"&author={quote(USER, safe='')}"
                    f"&per_page=100&page={page}"
                )

                commits = safe_request_json(
                    url,
                    context=f"{repo_label} commits branch {branch_name} page {page}",
                )

                if not commits:
                    break

                for commit in commits:
                    sha = commit.get("sha")
                    if sha:
                        seen_commits.add(sha)

                if len(commits) < 100:
                    break

                page += 1

        repo_commit_count_after = len(seen_commits)
        repo_added_commits = repo_commit_count_after - repo_commit_count_before

        print(f"{repo_label} added unique commits: {repo_added_commits}")

    print("Commit scan summary:")
    print(f"Public repos checked: {total_public_repos_checked}")
    print(f"Private repos checked: {total_private_repos_checked}")
    print(f"Branches checked: {total_branches_checked}")
    print(f"Unique commits found: {len(seen_commits)}")

    return len(seen_commits)

def get_contributions():
    years_query = """
    query($login: String!) {
      user(login: $login) {
        name
        login
        createdAt
        contributionsCollection {
          contributionYears
        }
      }
    }
    """

    user = graphql(years_query, {"login": USER})["user"]

    if not user:
        raise SystemExit(f"User not found: {USER}")

    years = user["contributionsCollection"]["contributionYears"] or [date.today().year]

    contribution_query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    now = datetime.now(timezone.utc)

    totals = {
        "commits": 0,
        "issues": 0,
        "prs": 0,
        "repo_contribs": 0,
        "contribs": 0,
    }

    day_counts = {}

    for year in sorted(years):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        if year == now.year:
            end = now

        data = graphql(
            contribution_query,
            {
                "login": USER,
                "from": start.isoformat().replace("+00:00", "Z"),
                "to": end.isoformat().replace("+00:00", "Z"),
            },
        )

        collection = data["user"]["contributionsCollection"]
        calendar = collection["contributionCalendar"]

        # These are GitHub profile-style contribution numbers.
        # Later we override commits, PRs, and issues with broader activity counts.
        totals["commits"] += collection["totalCommitContributions"]
        totals["issues"] += collection["totalIssueContributions"]
        totals["prs"] += collection["totalPullRequestContributions"]
        totals["repo_contribs"] += collection["totalRepositoryContributions"]
        totals["contribs"] += calendar["totalContributions"]

        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                day_counts[day["date"]] = day["contributionCount"]

    return user, totals, day_counts


def local_today():
    tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
    return datetime.now(tz).date()


def compute_streak(day_counts):
    if not day_counts:
        return 0, None, 0, None, None

    today = local_today()
    first_day = min(date.fromisoformat(day) for day in day_counts)
    counts = {date.fromisoformat(day): count for day, count in day_counts.items()}

    current = 0
    start_day = today if counts.get(today, 0) > 0 else today - timedelta(days=1)
    cursor = start_day

    while cursor >= first_day and counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    current_start = cursor + timedelta(days=1) if current else None

    longest = 0
    longest_start = None
    longest_end = None
    run = 0
    run_start = None
    cursor = first_day

    while cursor <= today:
        if counts.get(cursor, 0) > 0:
            if run == 0:
                run_start = cursor

            run += 1

            if run > longest:
                longest = run
                longest_start = run_start
                longest_end = cursor
        else:
            run = 0
            run_start = None

        cursor += timedelta(days=1)

    return current, current_start, longest, longest_start, longest_end


def fmt_date(value):
    if not value:
        return "No active streak"

    try:
        return value.strftime("%b %-d, %Y")
    except ValueError:
        return value.strftime("%b %#d, %Y")


def svg_text(x, y, text, size=14, fill="#e6edf3", weight="400", anchor="start"):
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}" '
        f'font-family="Inter, Segoe UI, Arial, sans-serif">'
        f'{escape(str(text))}</text>'
    )


def grade_for(score):
    if score >= 350:
        return "A+", 0.86
    if score >= 220:
        return "A", 0.76
    if score >= 120:
        return "B+", 0.64
    if score >= 60:
        return "B", 0.52

    return "C", 0.42


def build_svg(user, totals, repos, languages, day_counts, streak):
    owned_repos = [
        repo
        for repo in repos
        if repo.get("owner", {}).get("login", "").lower() == USER.lower()
        and not repo.get("fork")
    ]

    stars = sum(repo.get("stargazers_count", 0) for repo in owned_repos)
    contributed_to = len([repo for repo in repos if not repo.get("fork")])

    current, current_start, longest, longest_start, longest_end = streak

    score = (
        stars * 4
        + totals["commits"] * 0.45
        + totals["prs"] * 3
        + totals["issues"] * 2
        + totals["contribs"] * 0.08
    )

    grade, progress = grade_for(score)

    circumference = 2 * math.pi * 32
    dash = circumference * progress

    total_language_size = sum(size for _, size in languages) or 1
    language_percentages = [
        (name, size, (size / total_language_size) * 100)
        for name, size in languages
    ]

    if day_counts:
        min_year = min(int(day[:4]) for day in day_counts)
        contribution_range = f"{min_year} - Present"
    else:
        contribution_range = "All time"

    svg = []

    svg.append(
        """
<svg width="860" height="430" viewBox="0 0 860 430" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Analytics">
<rect x="1" y="1" width="858" height="428" fill="#0d1117" stroke="#30363d"/>
<line x1="430" y1="1" x2="430" y2="429" stroke="#30363d"/>
"""
    )

    # Top-left statistics card
    svg.append('<rect x="16" y="20" width="392" height="155" rx="4" fill="#071126" stroke="#c9d1d9"/>')
    svg.append(svg_text(36, 48, "My GitHub Statistics", 15, "#00aaff", "700"))

    stats = [
        ("★", "Total Stars:", stars),
        ("↻", "Total Commits:", totals["commits"]),
        ("⑂", "Total PRs:", totals["prs"]),
        ("ⓘ", "Total Issues:", totals["issues"]),
        ("▣", "Contributed to:", contributed_to),
    ]

    y = 76

    for icon, label, value in stats:
        svg.append(svg_text(36, y, icon, 14, "#00ffd0", "700"))
        svg.append(svg_text(56, y, label, 12, "#ffffff", "700"))
        svg.append(svg_text(172, y, value, 12, "#ffffff", "700"))
        y += 20

    svg.append('<circle cx="325" cy="107" r="32" stroke="#0e4670" stroke-width="5"/>')
    svg.append(
        f'<circle cx="325" cy="107" r="32" stroke="#00aaff" stroke-width="5" '
        f'stroke-linecap="round" stroke-dasharray="{dash:.1f} {circumference:.1f}" '
        f'transform="rotate(-90 325 107)"/>'
    )
    svg.append(svg_text(325, 113, grade, 22, "#ffffff", "800", "middle"))

    # Bottom-left streak card
    svg.append('<rect x="16" y="242" width="392" height="166" rx="4" fill="#161616"/>')
    svg.append('<line x1="145" y1="264" x2="145" y2="388" stroke="#c9d1d9"/>')
    svg.append('<line x1="278" y1="264" x2="278" y2="388" stroke="#c9d1d9"/>')

    svg.append(svg_text(82, 308, totals["contribs"], 24, "#ffffff", "800", "middle"))
    svg.append(svg_text(82, 338, "Total Contributions", 11, "#ffffff", "600", "middle"))
    svg.append(svg_text(82, 361, contribution_range, 9, "#8b949e", "400", "middle"))

    svg.append('<circle cx="212" cy="300" r="33" stroke="#ff8c00" stroke-width="4"/>')
    svg.append(svg_text(212, 307, current, 24, "#ffffff", "800", "middle"))
    svg.append(svg_text(212, 339, "Current Streak", 11, "#ff9800", "700", "middle"))
    svg.append(svg_text(212, 363, fmt_date(current_start), 9, "#8b949e", "400", "middle"))

    svg.append(svg_text(344, 308, longest, 24, "#ffffff", "800", "middle"))
    svg.append(svg_text(344, 338, "Longest Streak", 11, "#ffffff", "600", "middle"))

    if longest_start and longest_end:
        longest_label = f"{fmt_date(longest_start)} - {fmt_date(longest_end)}"
    else:
        longest_label = "No streak yet"

    svg.append(svg_text(344, 361, longest_label, 8, "#8b949e", "400", "middle"))

    # Right language card
    svg.append('<rect x="468" y="120" width="330" height="180" rx="4" fill="#071126" stroke="#c9d1d9"/>')
    svg.append(svg_text(492, 154, "My Programming Languages", 18, "#00aaff", "700"))

    bar_x = 492
    bar_y = 174
    bar_width = 284
    bar_height = 7
    current_x = bar_x

    for index, (name, size, percentage) in enumerate(language_percentages):
        width = bar_width * percentage / 100
        color = LANG_COLORS.get(name, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])

        svg.append(
            f'<rect x="{current_x:.1f}" y="{bar_y}" width="{max(width, 2):.1f}" '
            f'height="{bar_height}" fill="{color}"/>'
        )

        current_x += width

    for index, (name, size, percentage) in enumerate(language_percentages):
        column = 0 if index % 2 == 0 else 1
        row = index // 2

        lx = 496 + column * 142
        ly = 205 + row * 24

        color = LANG_COLORS.get(name, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        label = f"{name} ({percentage:.2f}%)"

        svg.append(f'<circle cx="{lx}" cy="{ly - 4}" r="5" fill="{color}"/>')
        svg.append(svg_text(lx + 11, ly, label, 10, "#ffffff", "700"))

    svg.append("</svg>")

    return "\n".join(svg)


if __name__ == "__main__":
    print(f"Generating analytics for {USER}")

    user, totals, day_counts = get_contributions()
    repos = get_repos()

    print_repo_access_report(repos)

    # Replace strict GitHub profile contribution counts with broader activity counts.
    totals["prs"] = get_total_prs_from_search()
    totals["issues"] = get_total_issues_from_search()
    totals["commits"] = get_total_commits_from_repos(repos)

    languages = get_languages(repos)
    streak = compute_streak(day_counts)

    print("Final stats:")
    print(json.dumps(totals, indent=2))

    svg = build_svg(user, totals, repos, languages, day_counts, streak)

    with open(OUT, "w", encoding="utf-8") as file:
        file.write(svg)

    print(f"Generated {OUT}")
