#!/usr/bin/env python3
"""Self-hosted GitHub stat cards (standard library only).

Replaces github-readme-stats / github-readme-activity-graph, whose public
Vercel instances are often rate-limited or down.

    python scripts/cards.py --user YOUR_USER --out assets

Writes (dark + light of each):
    card-stats-*.svg     stars, commits, PRs, issues, repos, followers
    card-langs-*.svg     top languages by bytes
    card-activity-*.svg  contributions per week over the last 12 months

Uses GITHUB_TOKEN if set (the Actions token is enough for public data).
Each card is built independently: if one API call fails, the other cards
are still written and the old file for the failed one is left in place.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime
from pathlib import Path

API = "https://api.github.com"
FONT = "ui-sans-serif,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

THEME = {
    "dark":  dict(bg="#0d1117", border="#30363d", title="#e6edf3", text="#c9d1d9", sub="#8b949e",
                  accent="#00b4d8", grid="#21262d", track="#21262d"),
    "light": dict(bg="#ffffff", border="#d0d7de", title="#1f2328", text="#1f2328", sub="#57606a",
                  accent="#0077b6", grid="#e6eaef", track="#e6eaef"),
}

LANG_COLORS = {
    "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572a5", "Java": "#b07219",
    "HTML": "#e34c26", "CSS": "#663399", "PHP": "#4f5d95", "C++": "#f34b7d", "C": "#8a8a8a",
    "Dart": "#00b4ab", "Kotlin": "#a97bff", "Swift": "#f05138", "Go": "#00add8", "Rust": "#dea584",
    "Shell": "#89e051", "Vue": "#41b883", "SCSS": "#c6538c", "Jupyter Notebook": "#da5b0b",
    "C#": "#178600", "Ruby": "#701516", "R": "#198ce7", "Blade": "#f7523f", "Batchfile": "#c1f12e",
}
FALLBACK = ["#00b4d8", "#90e0ef", "#7ee787", "#d29922", "#f778ba", "#a371f7", "#ff7b72", "#79c0ff"]


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #

def call(path, token, body=None):
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(url, headers={"User-Agent": "profile-cards"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)


def fetch_profile(user, token):
    info = call(f"/users/{user}", token)
    repos, page = [], 1
    while True:
        batch = call(f"/users/{user}/repos?per_page=100&page={page}&type=owner", token)
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    own = [r for r in repos if not r["fork"]]

    langs = {}
    for r in own:
        if r["archived"]:
            continue
        try:
            for name, size in call(r["languages_url"], token).items():
                langs[name] = langs.get(name, 0) + size
        except urllib.error.HTTPError:
            pass

    def total(q):
        try:
            return call("/search/issues?per_page=1&q=" + urllib.parse.quote(q), token)["total_count"]
        except urllib.error.HTTPError:
            return 0

    try:
        commits = call("/search/commits?per_page=1&q=" + urllib.parse.quote(f"author:{user}"), token)["total_count"]
    except urllib.error.HTTPError:
        commits = 0

    return dict(
        name=info.get("name") or user,
        stars=sum(r["stargazers_count"] for r in own),
        repos=info["public_repos"],
        followers=info["followers"],
        commits=commits,
        prs=total(f"author:{user} type:pr"),
        issues=total(f"author:{user} type:issue"),
        langs=langs,
    )


def fetch_calendar(user, token):
    """Contribution calendar via GraphQL. Returns list of (date, count)."""
    query = ("query($u:String!){user(login:$u){contributionsCollection{contributionCalendar{"
             "totalContributions weeks{contributionDays{date contributionCount}}}}}}")
    data = call(API + "/graphql", token, {"query": query, "variables": {"u": user}})
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [(d["date"], d["contributionCount"]) for w in cal["weeks"] for d in w["contributionDays"]]
    return cal["totalContributions"], days


# --------------------------------------------------------------------------- #
# SVG helpers
# --------------------------------------------------------------------------- #

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shell(w, h, c, title, body, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(label)}" font-family="{FONT}">'
            f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>'
            f'<text x="24" y="36" font-size="16" font-weight="700" fill="{c["title"]}">{esc(title)}</text>'
            f'{body}</svg>')


def fmt(n):
    return f"{n / 1000:.1f}k" if n >= 10000 else f"{n:,}"


# --------------------------------------------------------------------------- #
# cards
# --------------------------------------------------------------------------- #

def stats_card(p, user, mode):
    c = THEME[mode]
    rows = [("Total Stars", p["stars"]), ("Commits (public)", p["commits"]), ("Pull Requests", p["prs"]),
            ("Issues", p["issues"]), ("Public Repos", p["repos"]), ("Followers", p["followers"])]
    body = []
    for i, (label, value) in enumerate(rows):
        y = 72 + i * 28
        body.append(f'<circle cx="30" cy="{y - 4}" r="4" fill="{c["accent"]}"/>'
                    f'<text x="44" y="{y}" font-size="14" fill="{c["text"]}">{esc(label)}</text>'
                    f'<text x="390" y="{y}" font-size="14" font-weight="700" text-anchor="end" '
                    f'fill="{c["title"]}">{fmt(value)}</text>')
    return shell(420, 72 + 6 * 28 + 4, c, f"{p['name']}'s GitHub Stats", "".join(body), f"GitHub stats for {user}")


def langs_card(p, user, mode, limit=6):
    c = THEME[mode]
    ranked = sorted(p["langs"].items(), key=lambda kv: kv[1], reverse=True)[:limit]
    total = sum(v for _, v in ranked) or 1
    bar_x, bar_w, bar_y = 24, 372, 54
    x = bar_x
    body = [f'<clipPath id="r"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5"/></clipPath>',
            f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="10" rx="5" fill="{c["track"]}"/>',
            '<g clip-path="url(#r)">']
    colors = []
    for i, (name, size) in enumerate(ranked):
        col = LANG_COLORS.get(name, FALLBACK[i % len(FALLBACK)])
        colors.append(col)
        w = bar_w * size / total
        body.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{w + 0.5:.1f}" height="10" fill="{col}"/>')
        x += w
    body.append('</g>')
    for i, ((name, size), col) in enumerate(zip(ranked, colors)):
        cx, cy = 24 + (i % 2) * 190, 96 + (i // 2) * 26
        body.append(f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{col}"/>'
                    f'<text x="{cx + 16}" y="{cy}" font-size="13" fill="{c["text"]}">{esc(name)}</text>'
                    f'<text x="{cx + 170}" y="{cy}" font-size="12" text-anchor="end" fill="{c["sub"]}">{100 * size / total:.1f}%</text>')
    rows = (len(ranked) + 1) // 2
    return shell(420, 96 + rows * 26 + 6, c, "Top Languages", "".join(body), f"Top languages for {user}")


def activity_card(total, days, user, mode):
    c = THEME[mode]
    days = days[-371:]
    weeks = [sum(n for _, n in days[i:i + 7]) for i in range(0, len(days), 7)]
    W, H, L, R, T, B = 860, 260, 46, 24, 58, 40
    top = max(max(weeks), 1)
    step = max(1, round(top / 4 / 5) * 5) if top > 8 else 2
    ymax = step * ((top + step - 1) // step)
    pw, ph = W - L - R, H - T - B
    xs = [L + pw * i / max(len(weeks) - 1, 1) for i in range(len(weeks))]
    ys = [T + ph * (1 - v / ymax) for v in weeks]

    body = []
    for k in range(0, ymax + 1, step):
        y = T + ph * (1 - k / ymax)
        body.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="{c["grid"]}"/>'
                    f'<text x="{L - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="{c["sub"]}">{k}</text>')

    seen, last_x = None, -100
    for i in range(0, len(days), 7):
        month = datetime.strptime(days[i][0], "%Y-%m-%d").strftime("%b")
        x = xs[i // 7]
        if month != seen:
            seen = month
            if x < W - R - 20 and x - last_x >= 40:   # skip labels that would collide
                body.append(f'<text x="{x:.1f}" y="{H - 14}" font-size="11" text-anchor="middle" fill="{c["sub"]}">{month}</text>')
                last_x = x

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{T + ph} {line} {xs[-1]:.1f},{T + ph}"
    body.append(f'<polygon points="{area}" fill="{c["accent"]}" fill-opacity="0.18"/>'
                f'<polyline points="{line}" fill="none" stroke="{c["accent"]}" stroke-width="2.5" '
                f'stroke-linejoin="round" stroke-linecap="round"/>')
    peak = weeks.index(max(weeks))
    body.append(f'<circle cx="{xs[peak]:.1f}" cy="{ys[peak]:.1f}" r="4" fill="{c["accent"]}"/>')
    body.append(f'<text x="{W - 24}" y="36" font-size="13" text-anchor="end" fill="{c["sub"]}">'
                f'{fmt(total)} contributions in the last year</text>')
    return shell(W, H, c, "Contribution Activity", "".join(body), f"Contribution activity for {user}")


# --------------------------------------------------------------------------- #

def write(out, name, builder):
    for mode in ("dark", "light"):
        path = out / f"{name}-{mode}.svg"
        path.write_text(builder(mode), encoding="utf-8")
        print("wrote", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", default="assets")
    a = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    failed = 0
    try:
        p = fetch_profile(a.user, token)
        write(out, "card-stats", lambda m: stats_card(p, a.user, m))
        if p["langs"]:
            write(out, "card-langs", lambda m: langs_card(p, a.user, m))
    except Exception as e:  # keep going so one failure doesn't block the rest
        print("stats/langs failed:", e, file=sys.stderr)
        failed += 1
    try:
        total, days = fetch_calendar(a.user, token)
        write(out, "card-activity", lambda m: activity_card(total, days, a.user, m))
    except Exception as e:
        print("activity failed:", e, file=sys.stderr)
        failed += 1
    sys.exit(1 if failed == 2 else 0)


if __name__ == "__main__":
    main()
