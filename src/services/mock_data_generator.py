# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
import random
import sqlite3
import sys
import time

# ── Scale presets ─────────────────────────────────────────────────────────────

SCALES: dict[str, dict[str, int]] = {
    "small": {"history": 100_000, "bookmarks": 1_000, "annotations": 500},
    "medium": {"history": 500_000, "bookmarks": 5_000, "annotations": 2_000},
    "large": {"history": 1_000_000, "bookmarks": 10_000, "annotations": 5_000},
    "xl": {"history": 5_000_000, "bookmarks": 50_000, "annotations": 20_000},
}

BATCH_SIZE = 50_000  # rows per executemany call
_POOL_SIZE = 80_000  # pre-generated (url, host, title) pool size

# ── Realistic data corpus ─────────────────────────────────────────────────────

DOMAINS = [
    "github.com",
    "stackoverflow.com",
    "youtube.com",
    "reddit.com",
    "docs.python.org",
    "developer.mozilla.org",
    "arxiv.org",
    "medium.com",
    "news.ycombinator.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "wikipedia.org",
    "en.wikipedia.org",
    "zh.wikipedia.org",
    "npmjs.com",
    "pypi.org",
    "crates.io",
    "pkg.go.dev",
    "aws.amazon.com",
    "cloud.google.com",
    "azure.microsoft.com",
    "docker.com",
    "kubernetes.io",
    "helm.sh",
    "react.dev",
    "vuejs.org",
    "angular.io",
    "svelte.dev",
    "rust-lang.org",
    "golang.org",
    "kotlinlang.org",
    "swift.org",
    "postgresql.org",
    "mysql.com",
    "redis.io",
    "mongodb.com",
    "grafana.com",
    "prometheus.io",
    "elastic.co",
    "notion.so",
    "obsidian.md",
    "figma.com",
]

SUBPATHS = [
    "/questions/{id}/how-to-{verb}-{noun}",
    "/watch?v={token}",
    "/r/{sub}/comments/{id}/{slug}",
    "/wiki/{noun}",
    "/package/{noun}",
    "/docs/{noun}/{verb}",
    "/blog/{year}/{month}/{slug}",
    "/issues/{id}",
    "/pull/{id}",
    "/releases/tag/v{major}.{minor}.{patch}",
    "/{noun}-{verb}-guide",
    "/tutorial/{noun}",
    "/reference/{noun}",
    "/en/stable/{noun}.html",
    "/search?q={noun}+{verb}",
    "/profile/{token}",
    "/repo/{noun}/{verb}",
    "/article/{id}/{slug}",
    "/{noun}",
    "/",
]

TITLE_TEMPLATES = [
    "How to {verb} {noun} in Python",
    "{noun} - Stack Overflow",
    "{noun} {verb} Tutorial | MDN Web Docs",
    "Understanding {noun} and {verb}",
    "{verb} {noun}: A Complete Guide",
    "GitHub - {token}/{noun}: {verb} library",
    "{noun} vs {noun2}: Which Should You Use?",
    "Getting Started with {noun}",
    "Advanced {noun} Techniques",
    "Debugging {noun} Issues",
    "{noun} Best Practices {year}",
    "Why {noun} is {adjective}",
    "The {adjective} Guide to {noun}",
    "{noun} — Wikipedia",
    "r/{sub} - {noun} {verb} discussion",
    "{noun} {major}.{minor} Release Notes",
    "Optimizing {noun} Performance",
    "Building a {noun} with {noun2}",
    "{verb}ing {noun} at Scale",
    "{noun} Cheat Sheet",
]

NOUNS = [
    "Python",
    "Rust",
    "Go",
    "TypeScript",
    "JavaScript",
    "React",
    "Vue",
    "Docker",
    "Kubernetes",
    "PostgreSQL",
    "Redis",
    "SQLite",
    "MongoDB",
    "async",
    "coroutine",
    "iterator",
    "generator",
    "decorator",
    "metaclass",
    "closure",
    "lambda",
    "recursion",
    "memoization",
    "caching",
    "indexing",
    "migration",
    "refactoring",
    "testing",
    "profiling",
    "benchmarking",
    "authentication",
    "authorization",
    "encryption",
    "hashing",
    "JWT",
    "REST",
    "GraphQL",
    "gRPC",
    "WebSocket",
    "HTTP2",
    "TLS",
    "CI/CD",
    "pipeline",
    "deployment",
    "container",
    "microservice",
    "algorithm",
    "data structure",
    "binary tree",
    "hash map",
    "heap",
    "machine learning",
    "neural network",
    "transformer",
    "embedding",
    "Linux",
    "bash",
    "shell",
    "terminal",
    "vim",
    "git",
]

VERBS = [
    "implement",
    "optimize",
    "debug",
    "refactor",
    "deploy",
    "configure",
    "integrate",
    "migrate",
    "test",
    "benchmark",
    "profile",
    "monitor",
    "parse",
    "serialize",
    "validate",
    "authenticate",
    "encrypt",
    "compress",
    "stream",
    "batch",
    "cache",
    "index",
    "query",
    "aggregate",
    "build",
    "compile",
    "package",
    "publish",
    "release",
    "version",
]

ADJECTIVES = [
    "fast",
    "efficient",
    "scalable",
    "reliable",
    "secure",
    "modern",
    "lightweight",
    "powerful",
    "flexible",
    "elegant",
    "idiomatic",
]

SUBREDDITS = [
    "programming",
    "python",
    "rust",
    "golang",
    "javascript",
    "webdev",
    "devops",
    "linux",
    "MachineLearning",
    "datascience",
    "sysadmin",
]

BROWSERS = [
    ("chrome", "Default"),
    ("edge", "Default"),
    ("firefox", "default"),
    ("brave", "Default"),
    ("chrome", "Profile 1"),
    ("vivaldi", "Default"),
    ("chromium", "Default"),
]

TAGS = [
    "python",
    "javascript",
    "rust",
    "go",
    "typescript",
    "linux",
    "docker",
    "kubernetes",
    "git",
    "sql",
    "react",
    "vue",
    "backend",
    "frontend",
    "devops",
    "security",
    "performance",
    "tutorial",
    "reference",
    "tool",
    "research",
    "article",
    "video",
    "discussion",
    "news",
    "read-later",
    "important",
    "work",
    "personal",
    "archive",
]

NOTE_TEMPLATES = [
    "Need to revisit this — {noun} implementation looks promising.",
    "Good reference for {noun} {verb}ing.",
    "Compare with the {noun} approach in the other project.",
    "TODO: apply {noun} pattern here.",
    "Bookmarked for the {noun} migration task.",
    "Useful {noun} cheat sheet.",
    "Check the {noun} section again before the release.",
    "Shared with the team — {noun} best practices.",
    "{noun} performance numbers are impressive.",
    "Follow up on {noun} {major}.{minor} changelog.",
]

# ── Timestamp range: last 3 years in Unix seconds ────────────────────────────

_NOW = int(time.time())
_THREE_YEARS_AGO = _NOW - 3 * 365 * 24 * 3600

# ── Internal helpers ──────────────────────────────────────────────────────────


def _tok() -> str:
    """Random 8-char alphanumeric token."""
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))


def _make_ctx() -> dict[str, str]:
    """Build a substitution context dict for format_map."""
    n = random.choice(NOUNS).lower().replace(" ", "-")
    v = random.choice(VERBS)
    return {
        "noun": n,
        "noun2": random.choice(NOUNS).lower().replace(" ", "-"),
        "verb": v,
        "adjective": random.choice(ADJECTIVES),
        "sub": random.choice(SUBREDDITS),
        "token": _tok(),
        "slug": f"{v}-{n}",
        "id": str(random.randint(100_000, 9_999_999)),
        "year": str(random.randint(2020, 2025)),
        "month": f"{random.randint(1, 12):02d}",
        "major": str(random.randint(1, 9)),
        "minor": str(random.randint(0, 20)),
        "patch": str(random.randint(0, 10)),
    }


def _fill(template: str) -> str:
    """Fill a template string with random corpus words."""
    return template.format_map(_make_ctx())


def _rand_url() -> tuple[str, str]:
    """Return (url, host)."""
    host = random.choice(DOMAINS)
    path = random.choice(SUBPATHS).format_map(_make_ctx())
    return f"https://{host}{path}", host


def _rand_title() -> str:
    return random.choice(TITLE_TEMPLATES).format_map(_make_ctx()).replace("-", " ").title()


def _build_url_title_pool() -> list[tuple[str, str, str]]:
    """Pre-generate (url, host, title) tuples to amortize string work across 1M rows."""
    pool = []
    for _ in range(_POOL_SIZE):
        ctx = _make_ctx()
        host = random.choice(DOMAINS)
        url = f"https://{host}{random.choice(SUBPATHS).format_map(ctx)}"
        title = random.choice(TITLE_TEMPLATES).format_map(ctx).replace("-", " ").title()
        pool.append((url, host, title))
    return pool


def _rand_ts() -> int:
    return random.randint(_THREE_YEARS_AGO, _NOW)


def _progress(label: str, done: int, total: int, elapsed: float) -> None:
    """Print a single overwriting progress line to stdout."""
    pct = done / total
    width = 30
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {done:>10,} / {total:,}  ({pct:.0%})  {elapsed:.1f}s elapsed")
    sys.stdout.flush()


# ── FTS trigger DDL (must match local_db.py exactly) ─────────────────────────

_TRIGGER_AI = (
    "CREATE TRIGGER IF NOT EXISTS history_ai AFTER INSERT ON history BEGIN"
    " INSERT INTO history_fts(rowid, url, title) VALUES (new.id, new.url, new.title);"
    " END"
)
_TRIGGER_AD = (
    "CREATE TRIGGER IF NOT EXISTS history_ad AFTER DELETE ON history BEGIN"
    " INSERT INTO history_fts(history_fts, rowid, url, title)"
    " VALUES('delete', old.id, old.url, old.title);"
    " END"
)
_TRIGGER_AU = (
    "CREATE TRIGGER IF NOT EXISTS history_au AFTER UPDATE ON history BEGIN"
    " INSERT INTO history_fts(history_fts, rowid, url, title)"
    " VALUES('delete', old.id, old.url, old.title);"
    " INSERT INTO history_fts(rowid, url, title) VALUES (new.id, new.url, new.title);"
    " END"
)


# ── Main entry point ──────────────────────────────────────────────────────────


def generate_mock_data(db_path: Path, scale: str = "large") -> None:
    """
    Populate *db_path* with synthetic stress-test data.

    The database must already exist and have its schema created (call
    LocalDatabase(db_path) first so _create_tables() runs).

    Progress is printed to stdout. All writes use a direct sqlite3 connection
    with aggressive PRAGMAs for maximum throughput.
    """
    counts = SCALES.get(scale, SCALES["large"])
    n_history = counts["history"]
    n_bookmarks = counts["bookmarks"]
    n_annotations = counts["annotations"]

    tag = "[HistorySync MOCK]"
    print(f"\n{tag} ══════════════════════════════════════════════")
    print(f"{tag}  Scale      : {scale}")
    print(f"{tag}  History    : {n_history:,} records")
    print(f"{tag}  Bookmarks  : {n_bookmarks:,}  (with tags)")
    print(f"{tag}  Annotations: {n_annotations:,}")
    print(f"{tag}  DB path    : {db_path}")
    print(f"{tag} ══════════════════════════════════════════════")

    conn = sqlite3.connect(db_path, timeout=60)
    try:
        _setup_fast_pragmas(conn, tag)
        try:
            _generate_history(conn, n_history, tag)
            _generate_bookmarks(conn, n_bookmarks, tag)
            _generate_annotations(conn, n_annotations, tag)
        finally:
            # Always restore safe PRAGMAs, even if generation fails midway,
            # so the database is not left with synchronous=OFF / journal_mode=MEMORY.
            _restore_safe_pragmas(conn, tag)
        _print_db_stats(conn, db_path, tag)
    finally:
        conn.close()


# ── Phase helpers ─────────────────────────────────────────────────────────────


def _setup_fast_pragmas(conn: sqlite3.Connection, tag: str) -> None:
    print(f"{tag} Applying fast-write PRAGMAs...")
    conn.execute("PRAGMA synchronous  = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA cache_size   = -65536")  # 64 MB
    conn.execute("PRAGMA temp_store   = MEMORY")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE")
    print(f"{tag}   synchronous=OFF  journal_mode=MEMORY  cache=64MB  locking=EXCLUSIVE")


def _restore_safe_pragmas(conn: sqlite3.Connection, tag: str) -> None:
    print(f"\n{tag} Restoring safe PRAGMAs...")
    conn.execute("PRAGMA locking_mode = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    conn.execute("PRAGMA optimize")
    print(f"{tag}   synchronous=NORMAL  journal_mode=WAL  locking=NORMAL  optimize=done")


def _generate_history(conn: sqlite3.Connection, total: int, tag: str) -> None:
    print(f"{tag} Generating {total:,} history records...")
    print(f"{tag}   Dropping FTS triggers for bulk insert...")
    conn.execute("DROP TRIGGER IF EXISTS history_ai")
    conn.execute("DROP TRIGGER IF EXISTS history_ad")
    conn.execute("DROP TRIGGER IF EXISTS history_au")
    print(f"{tag}   FTS triggers dropped — bulk insert starting (batch={BATCH_SIZE:,})")

    sql = """
        INSERT OR IGNORE INTO history
            (url, title, visit_time, visit_count, browser_type, profile_name,
             typed_count, visit_duration, first_visit_time)
        VALUES (?,?,?,?,?,?,?,?,?)
    """
    domain_sql = "INSERT OR IGNORE INTO domains (host) VALUES (?)"

    print(f"{tag}   Building URL/title pool ({_POOL_SIZE:,} entries)...")
    t_pool = time.monotonic()
    pool = _build_url_title_pool()
    pool_size = len(pool)
    print(f"{tag}   Pool ready in {time.monotonic() - t_pool:.1f}s")

    t0 = time.monotonic()
    inserted = 0
    domain_set: set[str] = set()

    while inserted < total:
        batch_size = min(BATCH_SIZE, total - inserted)

        # Bulk-generate all random values for this batch in one pass each
        pidx = random.choices(range(pool_size), k=batch_size)
        tss = random.choices(range(_THREE_YEARS_AGO, _NOW + 1), k=batch_size)
        vcs = random.choices([1, 2, 3, 5, 10, 20], weights=[50, 20, 10, 8, 7, 5], k=batch_size)
        tcs = random.choices([None, None, None, 0, 1, 2], k=batch_size)
        browsers = random.choices(BROWSERS, k=batch_size)
        fv_flags = random.choices((True, False), weights=(3, 7), k=batch_size)
        fv_offs = random.choices(range(86400 * 30), k=batch_size)
        vd_flags = random.choices((True, False), weights=(1, 2), k=batch_size)
        vd_vals = [round(random.uniform(10.0, 600.0), 1) for _ in range(batch_size)]

        rows: list[tuple] = []
        for i in range(batch_size):
            url, host, title = pool[pidx[i]]
            domain_set.add(host)
            ts = tss[i]
            browser, profile = browsers[i]
            rows.append(
                (
                    url,
                    title,
                    ts,
                    vcs[i],
                    browser,
                    profile,
                    tcs[i],
                    vd_vals[i] if vd_flags[i] else None,
                    ts - fv_offs[i] if fv_flags[i] else None,
                )
            )

        with conn:
            conn.executemany(sql, rows)
            if domain_set:
                conn.executemany(domain_sql, [(h,) for h in domain_set])
                domain_set.clear()

        inserted += batch_size
        _progress(tag, inserted, total, time.monotonic() - t0)

    elapsed = time.monotonic() - t0
    rate = total / elapsed if elapsed > 0 else 0
    print(f"\n{tag}   History insert done: {total:,} rows in {elapsed:.1f}s  ({rate:,.0f} rows/s)")

    print(f"{tag}   Rebuilding FTS index (trigram) — this may take a moment...")
    t1 = time.monotonic()
    conn.execute("INSERT INTO history_fts(history_fts) VALUES('rebuild')")
    conn.commit()
    print(f"{tag}   FTS rebuild done in {time.monotonic() - t1:.1f}s")

    print(f"{tag}   Restoring FTS triggers...")
    conn.execute(_TRIGGER_AI)
    conn.execute(_TRIGGER_AD)
    conn.execute(_TRIGGER_AU)
    print(f"{tag}   FTS triggers restored")


def _generate_bookmarks(conn: sqlite3.Connection, total: int, tag: str) -> None:
    print(f"{tag} Generating {total:,} bookmarks with tags...")
    t0 = time.monotonic()

    # Sample random URLs already in history
    rows_url = conn.execute("SELECT url, title FROM history ORDER BY RANDOM() LIMIT ?", (total,)).fetchall()
    actual = len(rows_url)
    if actual == 0:
        print(f"{tag}   No history rows found — skipping bookmarks")
        return
    if actual < total:
        print(f"{tag}   Only {actual:,} history rows available — generating {actual:,} bookmarks")

    bm_sql = """
        INSERT OR IGNORE INTO bookmarks (url, title, tags, bookmarked_at)
        VALUES (?, ?, ?, ?)
    """
    tag_sql = """
        INSERT OR IGNORE INTO bookmark_tags (bookmark_id, tag) VALUES (?, ?)
    """

    bm_rows = [(url, title, "", _rand_ts()) for url, title in rows_url]
    with conn:
        conn.executemany(bm_sql, bm_rows)

    # Fetch inserted bookmark ids to attach tags
    bm_ids = conn.execute("SELECT id, url FROM bookmarks ORDER BY id DESC LIMIT ?", (actual,)).fetchall()

    tag_rows: list[tuple[int, str]] = []
    for bm_id, _ in bm_ids:
        n_tags = random.randint(1, 4)
        chosen = random.sample(TAGS, min(n_tags, len(TAGS)))
        for t in chosen:
            tag_rows.append((bm_id, t))

    with conn:
        conn.executemany(tag_sql, tag_rows)

    elapsed = time.monotonic() - t0
    print(f"{tag}   Bookmarks done: {actual:,} bookmarks, {len(tag_rows):,} tag entries in {elapsed:.1f}s")


def _generate_annotations(conn: sqlite3.Connection, total: int, tag: str) -> None:
    print(f"{tag} Generating {total:,} annotations...")
    t0 = time.monotonic()

    rows_url = conn.execute("SELECT url FROM history ORDER BY RANDOM() LIMIT ?", (total,)).fetchall()
    actual = len(rows_url)
    if actual == 0:
        print(f"{tag}   No history rows found — skipping annotations")
        return

    ann_sql = """
        INSERT OR IGNORE INTO annotations (url, note, created_at, updated_at)
        VALUES (?, ?, ?, ?)
    """
    ann_rows = []
    for (url,) in rows_url:
        note = _fill(random.choice(NOTE_TEMPLATES))
        ts = _rand_ts()
        ann_rows.append((url, note, ts, ts))

    with conn:
        conn.executemany(ann_sql, ann_rows)

    elapsed = time.monotonic() - t0
    print(f"{tag}   Annotations done: {actual:,} rows in {elapsed:.1f}s")


def _print_db_stats(conn: sqlite3.Connection, db_path: Path, tag: str) -> None:
    history_count = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    bookmark_count = conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    tag_count = conn.execute("SELECT COUNT(*) FROM bookmark_tags").fetchone()[0]
    annotation_count = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    domain_count = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    db_size_mb = (page_count * page_size) / (1024 * 1024)
    try:
        file_size_mb = db_path.stat().st_size / (1024 * 1024)
        size_str = f"{file_size_mb:.1f} MB (file) / {db_size_mb:.1f} MB (pages)"
    except OSError:
        size_str = f"{db_size_mb:.1f} MB (pages)"

    print(f"\n{tag} ══════════════════════════════════════════════")
    print(f"{tag}  FINAL DB STATS")
    print(f"{tag}  History records : {history_count:>12,}")
    print(f"{tag}  Domains         : {domain_count:>12,}")
    print(f"{tag}  Bookmarks       : {bookmark_count:>12,}")
    print(f"{tag}  Bookmark tags   : {tag_count:>12,}")
    print(f"{tag}  Annotations     : {annotation_count:>12,}")
    print(f"{tag}  DB size         : {size_str}")
    print(f"{tag} ══════════════════════════════════════════════\n")
