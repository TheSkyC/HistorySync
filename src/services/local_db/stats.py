# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Aggregation queries powering the stats dashboards.

Daily / hourly / browser / domain breakdowns all call the shared filter SQL
fragments :meth:`_HiddenMixin._hr_filter` and :meth:`_HiddenMixin._hd_filter`
(via ``self.``) so the visible counts always match the visible history rows.
"""

from __future__ import annotations

from src.utils.logger import get_logger

log = get_logger("local_db")


class _StatsMixin:
    """Daily / hourly / browser / top-domain aggregations."""

    @staticmethod
    def _time_range(year: int | None, month: int | None = None) -> tuple[int, int] | None:
        """Return (start_ts, end_ts) for the given year/month, or None for all-time.

        Boundaries are computed as local midnight to match the 'localtime' modifier
        used in SQL queries.  fold=0 is passed to datetime to resolve DST-ambiguous
        wall-clock times (e.g. the repeated hour when clocks fall back) consistently.
        """
        import datetime as _dt

        if year is None:
            return None
        if month is not None:
            next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
            start = int(_dt.datetime(year, month, 1, fold=0).timestamp())
            end = int(_dt.datetime(next_year, next_month, 1, fold=0).timestamp())
            return start, end
        start = int(_dt.datetime(year, 1, 1, fold=0).timestamp())
        end = int(_dt.datetime(year + 1, 1, 1, fold=0).timestamp())
        return start, end

    def get_available_years(self) -> list[int]:
        """Return sorted list of years that have history records."""
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT DISTINCT CAST(strftime('%Y', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS yr "
                "FROM history ORDER BY yr"
            ).fetchall()
        return [r[0] for r in rows if r[0] is not None]

    def get_daily_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[str, int]:
        """Return {YYYY-MM-DD: count} for days with visits, filtered by year/month."""
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            with self._conn(write=False) as conn:  # type: ignore[attr-defined]
                rows = conn.execute(
                    f"SELECT strftime('%Y-%m-%d', visit_time, 'unixepoch', 'localtime') AS day, "
                    f"COUNT(*) AS cnt FROM history "
                    f"WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd} GROUP BY day ORDER BY day",
                    (start_ts, end_ts),
                ).fetchall()
        else:
            with self._conn(write=False) as conn:  # type: ignore[attr-defined]
                rows = conn.execute(
                    f"SELECT strftime('%Y-%m-%d', visit_time, 'unixepoch', 'localtime') AS day, "
                    f"COUNT(*) AS cnt FROM history WHERE {hr} AND {hd} GROUP BY day ORDER BY day"
                ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_browser_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[str, int]:
        """Return {browser_type: count}, optionally filtered to *year*/*month*."""
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                f"SELECT browser_type, COUNT(*) AS cnt FROM history "
                f"WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd} GROUP BY browser_type"
            )
            params: tuple = (start_ts, end_ts)
        else:
            sql = f"SELECT browser_type, COUNT(*) AS cnt FROM history WHERE {hr} AND {hd} GROUP BY browser_type"
            params = ()
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(sql, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_hourly_visit_counts(self, year: int | None = None, month: int | None = None) -> dict[int, int]:
        """Return {hour_0_to_23: count} for a heat-of-day chart."""
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                f"SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                f"COUNT(*) AS cnt FROM history "
                f"WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd} GROUP BY hr"
            )
            params: tuple = (start_ts, end_ts)
        else:
            sql = (
                f"SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                f"COUNT(*) AS cnt FROM history WHERE {hr} AND {hd} GROUP BY hr"
            )
            params = ()
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(sql, params).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_top_domains(
        self, limit: int = 10, year: int | None = None, month: int | None = None
    ) -> list[tuple[str, int]]:
        """Return [(domain, count)] for the most-visited domains."""
        hr = self._hr_filter("h")  # type: ignore[attr-defined]
        hd = self._hd_filter(domain_alias="d")  # type: ignore[attr-defined]
        tr = self._time_range(year, month)
        if tr is not None:
            start_ts, end_ts = tr
            sql = (
                f"SELECT d.host, COUNT(*) AS cnt FROM history h "
                f"JOIN domains d ON h.domain_id = d.id "
                f"WHERE h.visit_time >= ? AND h.visit_time < ? AND {hr} AND {hd} "
                f"GROUP BY d.host ORDER BY cnt DESC LIMIT ?"
            )
            params: tuple = (start_ts, end_ts, limit)
        else:
            sql = (
                f"SELECT d.host, COUNT(*) AS cnt FROM history h "
                f"JOIN domains d ON h.domain_id = d.id "
                f"WHERE {hr} AND {hd} GROUP BY d.host ORDER BY cnt DESC LIMIT ?"
            )
            params = (limit,)
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(sql, params).fetchall()
        return [(r[0], r[1]) for r in rows]

    def get_day_top_pages(self, date_str: str, limit: int = 3) -> list[tuple[str, str, int]]:
        """Return [(title, url, total_visits)] for the most-visited pages on *date_str* (YYYY-MM-DD)."""
        import datetime as _dt

        d = _dt.date.fromisoformat(date_str)
        start_ts = int(_dt.datetime(d.year, d.month, d.day).timestamp())
        end_ts = start_ts + 86400
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                f"SELECT MAX(title) AS title, url, SUM(visit_count) AS total_visits FROM history "
                f"WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd} "
                f"GROUP BY url ORDER BY total_visits DESC LIMIT ?",
                (start_ts, end_ts, limit),
            ).fetchall()
        return [(r[0] or r[1], r[1], r[2]) for r in rows]

    def get_day_hourly_counts(self, date_str: str) -> dict[int, int]:
        """Return {hour_0_to_23: count} for a specific date (YYYY-MM-DD)."""
        import datetime as _dt

        d = _dt.date.fromisoformat(date_str)
        start_ts = int(_dt.datetime(d.year, d.month, d.day).timestamp())
        end_ts = start_ts + 86400
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                f"SELECT CAST(strftime('%H', visit_time, 'unixepoch', 'localtime') AS INTEGER) AS hr, "
                f"COUNT(*) AS cnt FROM history "
                f"WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd} GROUP BY hr",
                (start_ts, end_ts),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_day_counts_batch(
        self,
        day_starts: list[int],
        hidden_only: bool = False,
        keyword: str = "",
        browser_type: str = "",
        excluded_ids: set[int] | None = None,
        domain_ids: list[int] | None = None,
        excludes: list[str] | None = None,
        title_only: bool = False,
        url_only: bool = False,
        bookmarked_only: bool = False,
        has_annotation: bool = False,
        bookmark_tag: str = "",
        device_ids: list[int] | None = None,
    ) -> dict[int, int]:
        """Return {day_start_ts: record_count} for every timestamp in *day_starts*.

        When filter params are provided, counts only records that match the
        active filters (keyword, browser, domain, etc.) so separator pills
        reflect the filtered result set rather than totals.

        When *hidden_only* is True, only hidden records are counted (mirroring
        the hidden-only view in the history page).

        Internally issues one ``get_filtered_count`` call per day; batch size
        is typically 3-10 visible separator rows so total cost is negligible.
        """
        if not day_starts:
            return {}
        result: dict[int, int] = {}
        for day_start in day_starts:
            result[day_start] = self.get_filtered_count(  # type: ignore[attr-defined]
                keyword=keyword,
                browser_type=browser_type,
                date_from=day_start,
                date_to=day_start + 86399,
                excluded_ids=excluded_ids,
                domain_ids=domain_ids,
                excludes=excludes,
                title_only=title_only,
                url_only=url_only,
                bookmarked_only=bookmarked_only,
                has_annotation=has_annotation,
                bookmark_tag=bookmark_tag,
                device_ids=device_ids,
                hidden_only=hidden_only,
            )
        return result

    def get_day_rank(self, day_start_ts: int, ts: int) -> int:
        """Return the 1-based rank of ts among all records in the same day (ordered by visit_time)."""
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                f"SELECT COUNT(*) FROM history WHERE visit_time >= ? AND visit_time <= ? AND {hr} AND {hd}",
                (day_start_ts, ts),
            ).fetchone()
        return row[0] if row else 1

    def get_day_stats(self, day_start_ts: int, day_end_ts: int, top_n: int = 3) -> dict:
        """Return stats for a given day used by the scroll time bubble.

        Uses a half-open interval [day_start_ts, day_end_ts) so the boundary
        is consistent with get_day_hourly_counts (which uses start + 86400).

        Returns:
            {
                "total": int,          # total records for the day
                "domains": [(host, count), ...]  # top N domains by visit count
            }
        """
        hr_h = self._hr_filter("h")  # type: ignore[attr-defined]
        hr = self._hr_filter()  # type: ignore[attr-defined]
        hd = self._hd_filter()  # type: ignore[attr-defined]
        hd_d = self._hd_filter("h", domain_alias="d")  # type: ignore[attr-defined]
        with self._conn(write=False) as conn:  # type: ignore[attr-defined]
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM history WHERE visit_time >= ? AND visit_time < ? AND {hr} AND {hd}",
                (day_start_ts, day_end_ts),
            ).fetchone()
            total = total_row[0] if total_row else 0

            domain_rows = conn.execute(
                f"""
                SELECT d.host, COUNT(h.id) AS cnt
                FROM history h
                JOIN domains d ON h.domain_id = d.id
                WHERE h.visit_time >= ? AND h.visit_time < ?
                AND {hr_h} AND {hd_d}
                GROUP BY d.id
                ORDER BY cnt DESC
                LIMIT ?
                """,
                (day_start_ts, day_end_ts, top_n),
            ).fetchall()

        return {
            "total": total,
            "domains": [(r[0], r[1]) for r in domain_rows],
        }
