#!/usr/bin/env python3
"""
PowerPlus Instagram campaign publisher (cloud + local).

Token source: IG_TOKEN env var (GitHub Actions secret) if present,
otherwise token.txt beside this file (local runs).

Publishes the poster scheduled for today (Toronto) to @inceptastudio via the
Instagram Content Publishing API: create container -> poll FINISHED -> media_publish.

Guards:
  - Duplicate: never re-posts a poster number in posted.log.
  - Date: only posts the poster whose scheduled date == today (Toronto).
Usage:
  publish.py            # post today's scheduled poster (cron path)
  publish.py <n>        # force poster n
  publish.py --dry <n>  # build + poll status, do NOT publish
"""
import json, sys, time, urllib.parse, urllib.request, urllib.error, datetime, os

BASE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(BASE, name)) as f:
        return f.read().strip()


def load_token():
    tok = os.environ.get("IG_TOKEN", "").strip()
    if tok:
        return tok
    return load("token.txt")


CFG = json.loads(load("config.json"))
TOKEN = load_token()
CAPTIONS = json.loads(load("captions.json"))
GV = CFG["graph_version"]
IG = CFG["ig_user_id"]
LOG = os.path.join(BASE, "run.log")
POSTED = os.path.join(BASE, "posted.log")


def log(msg):
    line = f"{datetime.datetime.utcnow().isoformat()}Z  {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def already_posted(n):
    if not os.path.exists(POSTED):
        return False
    with open(POSTED) as f:
        return any(line.split("\t")[0] == str(n) for line in f if line.strip())


def mark_posted(n, media_id, permalink):
    with open(POSTED, "a") as f:
        f.write(f"{n}\t{media_id}\t{permalink}\t{datetime.datetime.utcnow().isoformat()}Z\n")


def api(method, path, params):
    url = f"https://graph.facebook.com/{GV}/{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        log(f"API ERROR {e.code}: {e.read().decode()}")
        raise


def poster_due_today():
    try:
        from zoneinfo import ZoneInfo
        today = datetime.datetime.now(ZoneInfo(CFG["timezone"])).date()
    except Exception:
        today = datetime.date.today()
    start = datetime.date.fromisoformat(CFG["first_scheduled_date"])
    delta = (today - start).days
    n = CFG["first_scheduled_poster"] + delta
    if delta >= 0 and CFG["first_scheduled_poster"] <= n <= CFG["last_poster"]:
        return n
    return None


def publish(n, dry=False):
    if already_posted(n):
        log(f"poster {n}: already posted — skipping (duplicate guard)")
        return
    entry = CAPTIONS.get(str(n))
    if not entry:
        log(f"poster {n}: NO CAPTION — aborting")
        return
    img = CFG["image_base_url"].format(n=f"{n:02d}")
    log(f"poster {n}: creating container  img={img}")
    c = api("POST", f"{IG}/media", {"image_url": img, "caption": entry["caption"], "access_token": TOKEN})
    cid = c.get("id")
    if not cid:
        log(f"poster {n}: container failed: {c}")
        return
    for _ in range(20):
        st = api("GET", cid, {"fields": "status_code", "access_token": TOKEN})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            log(f"poster {n}: container ERROR: {st}")
            return
        time.sleep(5)
    else:
        log(f"poster {n}: never FINISHED — aborting")
        return
    if dry:
        log(f"poster {n}: DRY RUN ok — container {cid} FINISHED, not published")
        return
    pub = api("POST", f"{IG}/media_publish", {"creation_id": cid, "access_token": TOKEN})
    mid = pub.get("id")
    if not mid:
        log(f"poster {n}: media_publish failed: {pub}")
        return
    perm = api("GET", mid, {"fields": "permalink", "access_token": TOKEN}).get("permalink", "")
    mark_posted(n, mid, perm)
    log(f"poster {n}: PUBLISHED  media_id={mid}  {perm}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    if args:
        publish(int(args[0]), dry=dry)
    else:
        n = poster_due_today()
        log("no poster scheduled for today — nothing to do") if n is None else publish(n, dry=dry)
