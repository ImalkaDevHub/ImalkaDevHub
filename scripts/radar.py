#!/usr/bin/env python3
"""Radar chart generator (standard library only).

Skill radar from a JSON file you edit:
    python scripts/radar.py --data assets/skills.json --out assets/radar

Language radar from your public repos (GitHub API):
    python scripts/radar.py --github YOUR_USER --out assets/radar-langs

Writes <out>-dark.svg and <out>-light.svg.
"""
import argparse, json, math, os, sys, urllib.request, urllib.error
from pathlib import Path

PALETTE = {
    "dark":  dict(ring="#30363d", spoke="#21262d", text="#c9d1d9", sub="#8b949e",
                  head="#e6edf3", area="#00b4d8", edge="#00b4d8", dot="#90e0ef"),
    "light": dict(ring="#d0d7de", spoke="#e6eaef", text="#1f2328", sub="#57606a",
                  head="#1f2328", area="#0077b6", edge="#0077b6", dot="#023e8a"),
}
FONT = "ui-sans-serif,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"


def load_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("title", "Skill Radar"), [(a["label"], float(a["value"])) for a in data["axes"]]


def get(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "radar-script"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def load_github(user, token, limit, skip, curve):
    totals, page = {}, 1
    while True:
        repos = get(f"https://api.github.com/users/{user}/repos?per_page=100&page={page}&type=owner", token)
        for repo in repos:
            if repo["fork"] or repo["archived"]:
                continue
            try:
                langs = get(repo["languages_url"], token)
            except urllib.error.HTTPError:
                continue
            for name, size in langs.items():
                if name.lower() not in skip:
                    totals[name] = totals.get(name, 0) + size
        if len(repos) < 100:
            break
        page += 1
    if not totals:
        sys.exit("No language data found.")
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    top = ranked[0][1]
    # curve < 1 stops one dominant language from flattening every other axis
    return f"{user} · language mix", [(n, round(100 * (b / top) ** curve, 1)) for n, b in ranked]


def polygon(n, radius):
    return [(radius * math.sin(2 * math.pi * i / n), -radius * math.cos(2 * math.pi * i / n)) for i in range(n)]


def pts(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def draw(title, axes, mode, radius=150, rings=4, show_values=False):
    col, n = PALETTE[mode], len(axes)
    side = max(len(label) for label, _ in axes) * 8 + 34   # room for the widest label
    W, H = 2 * (radius + max(side, 90)), 2 * radius + 120
    cx, cy = W / 2, radius + 78
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'role="img" aria-label="{escape(title)}" font-family="{FONT}">',
           f'<text x="{cx}" y="30" text-anchor="middle" font-size="16" font-weight="700" fill="{col["head"]}">{escape(title)}</text>',
           f'<g transform="translate({cx},{cy})">']

    for k in range(rings, 0, -1):
        out.append(f'<polygon points="{pts(polygon(n, radius * k / rings))}" fill="none" '
                   f'stroke="{col["ring"]}" opacity="{0.4 + 0.15 * k:.2f}"/>')
    corners = polygon(n, radius)
    for x, y in corners:
        out.append(f'<line x1="0" y1="0" x2="{x:.1f}" y2="{y:.1f}" stroke="{col["spoke"]}"/>')

    shape = [(x * v / 100, y * v / 100) for (x, y), (_, v) in zip(corners, axes)]
    out.append('<g><animateTransform attributeName="transform" type="scale" values="0.05;1" dur="1s" '
               'calcMode="spline" keyTimes="0;1" keySplines="0.22 1 0.36 1" fill="freeze"/>')
    out.append(f'<polygon points="{pts(shape)}" fill="{col["area"]}" fill-opacity="0.22" '
               f'stroke="{col["edge"]}" stroke-width="2.5" stroke-linejoin="round"/>')
    for x, y in shape:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{col["dot"]}" stroke="{col["edge"]}" stroke-width="1.5"/>')
    out.append('</g>')

    for (x, y), (label, value) in zip(corners, axes):
        ux, uy = x / radius, y / radius
        lx, ly = x + ux * 18, y + uy * 18
        anchor = "middle" if abs(ux) < 0.3 else ("start" if ux > 0 else "end")
        ly += 4 if abs(uy) < 0.3 else (16 if uy > 0 else -4)
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="13" '
                   f'font-weight="600" fill="{col["text"]}">{escape(label)}</text>')
        if show_values:
            out.append(f'<text x="{lx:.1f}" y="{ly + 14:.1f}" text-anchor="{anchor}" font-size="11" '
                       f'fill="{col["sub"]}">{value:g}</text>')
    out.append('</g></svg>')
    return "".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="assets/skills.json")
    ap.add_argument("--github", metavar="USER")
    ap.add_argument("--out", default="assets/radar")
    ap.add_argument("--limit", type=int, default=7)
    ap.add_argument("--curve", type=float, default=0.45)
    ap.add_argument("--skip", default="shell,makefile,dockerfile,batchfile,procfile")
    ap.add_argument("--values", action="store_true")
    a = ap.parse_args()

    if a.github:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        skip = {s.strip().lower() for s in a.skip.split(",") if s.strip()}
        title, axes = load_github(a.github, token, a.limit, skip, a.curve)
    else:
        title, axes = load_json(a.data)
    if len(axes) < 3:
        sys.exit("A radar chart needs at least 3 axes.")

    base = Path(a.out)
    base.parent.mkdir(parents=True, exist_ok=True)
    for mode in ("dark", "light"):
        target = base.with_name(f"{base.name}-{mode}.svg")
        target.write_text(draw(title, axes, mode, show_values=a.values), encoding="utf-8")
        print("wrote", target)


if __name__ == "__main__":
    main()
