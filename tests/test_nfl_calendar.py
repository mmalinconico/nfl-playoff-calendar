"""Offline NFL-specific calendar regression tests; no live ESPN/API calls."""
import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import fetch_events as fetch
import generate_calendar as generator
import validate_calendar


def opponent(name, side, team_id="1"):
    return {"homeAway": side, "team": {"id": team_id, "displayName": name}}


def recorded_event(**values):
    result = {
        "id": "test-game-1",
        "name": "Wild Card Playoffs",
        "date": "2027-01-16",
        "source": "espn",
        "espn_id": "test-game-1",
        "all_day": True,
        "uid": "wild-card-playoffs-test-game-1",
        "dtstamp": "20260903T212032Z",
    }
    result.update(values)
    return result


class FetchEventCases(unittest.TestCase):
    """Exercise the actual ESPN event assembly without an external request."""

    def one_game(self, *, week=1, competitors=None, date_text=None,
                 name="", previous=None, extra=None, venue=("Test Stadium", "Test City"),
                 broadcasts="CBS", refs=None):
        date_text = date_text or "2027-01-16T05:00:00Z"  # 00:00 Eastern, TBA
        event = {"date": date_text, "name": name}
        competition = {"competitors": competitors if competitors is not None else [],
                       "date": date_text}
        competition.update(extra or {})
        mapping = refs or {}

        def resolve(value, label):
            return mapping.get(value.get("$ref"), value)

        with patch.object(fetch, "fetch_core_postseason_event_refs",
                          return_value=[{"id": "401873999", "week": week, "$ref": "event"}]), \
             patch.object(fetch, "core_get_json", return_value=event), \
             patch.object(fetch, "core_competition_for_event", return_value=competition), \
             patch.object(fetch, "core_venue_details", return_value=venue), \
             patch.object(fetch, "core_broadcast_networks", return_value=broadcasts), \
             patch.object(fetch, "resolve_ref", side_effect=resolve):
            return fetch.fetch_core_postseason_events(2026, previous or [], "LXI")

    def test_wild_card_tba_becomes_all_day(self):
        events, excluded, _ = self.one_game()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "Wild Card Playoffs")
        self.assertEqual(events[0]["date"], "2027-01-16")
        self.assertTrue(events[0]["all_day"])
        self.assertEqual(events[0]["status"], "Kickoff time TBA")
        self.assertFalse(excluded)

    def test_divisional_and_conference_placeholders(self):
        for week, name in ((2, "Divisional Playoffs"),
                           (3, "Conference Championship")):
            with self.subTest(week=week):
                events, _, _ = self.one_game(week=week)
                self.assertEqual(events[0]["name"], name)

    def test_afc_nfc_labels_are_preserved(self):
        for label in ("AFC Championship", "NFC Championship"):
            with self.subTest(label=label):
                events, _, _ = self.one_game(week=3, name=label)
                self.assertEqual(events[0]["name"], label)

    def test_known_away_home_irrespective_of_competitor_order(self):
        sides = [opponent("New York Jets", "home", "20"),
                 opponent("Buffalo Bills", "away", "2")]
        for competitors in (sides, list(reversed(sides))):
            with self.subTest(order=competitors[0]["homeAway"]):
                events, _, _ = self.one_game(competitors=competitors)
                self.assertEqual(events[0]["name"],
                                 "Buffalo Bills @ New York Jets")

    def test_away_jets_and_other_cities(self):
        for teams, title in (
            ([opponent("New York Jets", "away", "20"),
              opponent("Buffalo Bills", "home", "2")],
             "New York Jets @ Buffalo Bills"),
            ([opponent("Kansas City Chiefs", "away", "12"),
              opponent("Baltimore Ravens", "home", "33")],
             "Kansas City Chiefs @ Baltimore Ravens"),
        ):
            with self.subTest(title=title):
                events, _, _ = self.one_game(competitors=teams)
                self.assertEqual(events[0]["name"], title)

    def test_missing_side_or_tbd_team_keeps_round_name(self):
        for competitors in (
            [opponent("New York Jets", "home", "20")],
            [opponent("TBD", "away"), opponent("Buffalo Bills", "home", "2")],
            [{"team": {"displayName": "New York Jets"}},
             opponent("Buffalo Bills", "home", "2")],
        ):
            with self.subTest(competitors=competitors):
                events, _, _ = self.one_game(competitors=competitors)
                self.assertEqual(events[0]["name"], "Wild Card Playoffs")

    def test_giants_excluded_at_home_or_away(self):
        for side in ("home", "away"):
            with self.subTest(side=side):
                otherside = "away" if side == "home" else "home"
                teams = [opponent("New York Giants", side, "19"),
                         opponent("Dallas Cowboys", otherside, "6")]
                events, ids, _ = self.one_game(competitors=teams)
                self.assertEqual(events, [])
                self.assertEqual(ids, {"401873999"})

    def test_giants_team_ref_is_excluded_even_with_generic_event_label(self):
        teams = [
            {"$ref": "https://example.test/competitors/a"},
            {"$ref": "https://example.test/competitors/b"},
        ]
        resolved = {
            "https://example.test/competitors/a": {
                "homeAway": "away",
                "team": {"$ref": "https://example.test/teams/19"},
            },
            "https://example.test/competitors/b": {
                "homeAway": "home",
                "team": {"id": "20", "displayName": "New York Jets"},
            },
            "https://example.test/teams/19": {
                "id": "19", "displayName": "New York Giants"
            },
        }
        events, ids, _ = self.one_game(competitors=teams, refs=resolved)
        self.assertEqual(events, [])
        self.assertEqual(ids, {"401873999"})

    def test_kickoff_valid_makes_four_hour_timed_event(self):
        events, _, _ = self.one_game(
            date_text="2027-01-16T21:30:00Z",
            extra={"timeValid": True},
        )
        self.assertNotIn("all_day", events[0])
        self.assertEqual(events[0]["date"], "2027-01-16T21:30:00Z")
        lines = generator.serialize_event(recorded_event(
            date=events[0]["date"], all_day=False
        ))
        self.assertIn("DTSTART:20270116T213000Z", lines)
        self.assertIn("DTEND:20270117T013000Z", lines)

    def test_timevalid_false_makes_all_day(self):
        events, _, _ = self.one_game(
            date_text="2027-01-17T21:30:00Z",
            extra={"timeValid": False},
        )
        self.assertEqual(events[0]["date"], "2027-01-17")
        self.assertTrue(events[0]["all_day"])

    def test_temporary_kickoff_regression_keeps_known_time_on_same_day(self):
        previous = [recorded_event(
            id="401873999", espn_id="401873999",
            date="2027-01-16T21:30:00Z", all_day=False,
        )]
        events, _, _ = self.one_game(previous=previous)
        self.assertEqual(events[0]["date"], "2027-01-16T21:30:00Z")
        self.assertNotIn("all_day", events[0])

    def test_legitimate_date_move_is_allowed(self):
        previous = [recorded_event(
            id="401873999", espn_id="401873999",
            date="2027-01-16T21:30:00Z", all_day=False,
        )]
        events, _, _ = self.one_game(
            previous=previous, date_text="2027-01-17T05:00:00Z"
        )
        self.assertEqual(events[0]["date"], "2027-01-17")
        self.assertTrue(events[0]["all_day"])

    def test_missing_venue_and_network_reuse_known_values(self):
        previous = [recorded_event(
            id="401873999", espn_id="401873999",
            venue="Previous Stadium", city="Previous City",
            network="FOX"
        )]
        events, _, _ = self.one_game(
            previous=previous, venue=("", ""), broadcasts="TBA"
        )
        self.assertEqual(events[0]["venue"], "Previous Stadium")
        self.assertEqual(events[0]["city"], "Previous City")
        self.assertEqual(events[0]["network"], "FOX")

    def test_super_bowl_neutral_site_matchup_stable_id_and_streaming(self):
        teams = [opponent("Kansas City Chiefs", "away", "12"),
                 opponent("San Francisco 49ers", "home", "25")]
        events, _, _ = self.one_game(
            week=4, date_text="2027-02-14T23:30:00Z",
            competitors=teams, venue=("SoFi Stadium", "Inglewood"),
            broadcasts="ESPN / ABC",
        )
        sb = events[0]
        self.assertEqual(sb["name"],
                         "Kansas City Chiefs @ San Francisco 49ers")
        self.assertEqual(sb["id"], "super-bowl-lxi")
        self.assertEqual(sb["uid"], "super-bowl-lxi@nfl-playoff-calendar")
        self.assertEqual(sb["streaming"], "ESPN App / Disney+")
        self.assertEqual(sb["venue"], "SoFi Stadium")

    def test_super_bowl_tbd_name_and_uid(self):
        events, _, _ = self.one_game(
            week=4, date_text="2027-02-14T23:30:00Z"
        )
        self.assertEqual(events[0]["name"], "Super Bowl LXI")
        self.assertEqual(events[0]["uid"],
                         "super-bowl-lxi@nfl-playoff-calendar")

    def test_future_super_bowl_handoff_preserves_uid_and_metadata(self):
        previous = [fetch.future_super_bowl_calendar_event({
            "roman": "LXI", "date": "2027-02-14", "venue": "SoFi Stadium",
            "city": "Inglewood", "network": "ESPN / ABC",
        })]
        previous[0]["dtstamp"] = "20260903T212032Z"
        events, _, _ = self.one_game(
            week=4, date_text="2027-02-14T23:30:00Z",
            previous=previous, venue=("", ""), broadcasts="TBD",
        )
        fetch.assign_stable_metadata(events, previous)
        self.assertEqual(events[0]["uid"], previous[0]["uid"])
        self.assertEqual(events[0]["venue"], "SoFi Stadium")
        self.assertEqual(events[0]["network"], "ESPN / ABC")
        self.assertNotEqual(events[0]["dtstamp"], previous[0]["dtstamp"])

    def test_english_tv_filter_and_names(self):
        sample = [
            {"name": "CBS", "language": "English"},
            {"name": "ESPN Deportes", "language": "Spanish"},
            {"name": "FOX", "language": "en"},
            {"name": "Telemundo"},
            {"name": "ABC"},
        ]
        with patch.object(fetch, "core_collection_items", return_value=sample):
            self.assertEqual(fetch.core_broadcast_networks("123"),
                             "CBS / FOX / ABC")

    def test_non_super_bowl_streaming_is_never_serialized(self):
        item = recorded_event(streaming="Some Platform", network="NBC")
        description = next(x for x in generator.serialize_event(item)
                           if x.startswith("DESCRIPTION:"))
        self.assertEqual(description, "DESCRIPTION:Network: NBC")

    def test_super_bowl_streaming_is_separate_from_television(self):
        item = recorded_event(
            id="super-bowl-lxi", uid=fetch.super_bowl_uid("LXI"),
            network="ESPN / ABC", streaming="ESPN App / Disney+")
        description = next(x for x in generator.serialize_event(item)
                           if x.startswith("DESCRIPTION:"))
        self.assertEqual(description,
                         "DESCRIPTION:Network: ESPN / ABC\\nStreaming: ESPN App / Disney+")


class FutureAndReliabilityCases(unittest.TestCase):
    def setUp(self):
        self.today = patch.object(fetch, "calendar_today",
                                  return_value=date(2026, 10, 9))
        self.today.start()
        self.addCleanup(self.today.stop)

    @staticmethod
    def candidate(roman, year, date_text=None):
        return {
            "roman": roman, "year": year, "wikipedia_date": date_text,
            "venue": "Future Stadium", "city": "Future City",
            "network": "CBS", "discovery_source_url": "https://example.test"
        }

    def discover(self, candidates, confirmed, seen, nfl=None, previous=None):
        with patch.object(fetch, "wikipedia_future_super_bowl_candidates",
                          return_value=candidates), \
             patch.object(fetch, "cbs_verified_future_dates",
                          return_value=(confirmed, seen)), \
             patch.object(fetch, "nfl_operations_verified_future_dates",
                          return_value=nfl or {}):
            return fetch.discover_verified_future_super_bowls(previous or [])

    def test_unverified_future_date_is_not_published(self):
        events, _, _ = self.discover(
            [self.candidate("LXIII", 2029, "2029-02-11")],
            {}, {"LXIII"})
        self.assertEqual(events, [])

    def test_verified_future_date_is_published(self):
        events, _, _ = self.discover(
            [self.candidate("LXII", 2028, "2028-02-13")],
            {"LXII": "2028-02-13"}, {"LXII"})
        self.assertEqual(len(events), 1)
        placeholder = fetch.future_super_bowl_calendar_event(events[0])
        self.assertEqual(placeholder["uid"],
                         "super-bowl-lxii@nfl-playoff-calendar")
        self.assertEqual(placeholder["date"], "2028-02-13")
        self.assertEqual(placeholder["streaming"], "Paramount+")

    def test_independent_source_disagreement_blocks_publication(self):
        events, _, _ = self.discover(
            [self.candidate("LXII", 2028)],
            {"LXII": "2028-02-13"}, {"LXII"},
            nfl={"LXII": "2028-02-20"})
        self.assertEqual(events, [])

    def test_wikipedia_date_conflict_blocks_publication(self):
        events, _, _ = self.discover(
            [self.candidate("LXII", 2028, "2028-02-20")],
            {"LXII": "2028-02-13"}, {"LXII"})
        self.assertEqual(events, [])

    def test_no_streaming_never_blocks_future_super_bowl(self):
        event = fetch.future_super_bowl_calendar_event({
            "roman": "LXIII", "date": "2029-02-11",
            "venue": "Future Stadium", "city": "Future City", "network": "FOX"
        })
        self.assertEqual(event["date"], "2029-02-11")
        self.assertNotIn("streaming", event)

    def test_future_super_bowl_metadata_does_not_regress_to_tba(self):
        previous = fetch.future_super_bowl_calendar_event({
            "roman": "LXII", "date": "2028-02-13",
            "venue": "Mercedes-Benz Stadium", "city": "Atlanta",
            "network": "CBS",
        })
        current = fetch.future_super_bowl_calendar_event({
            "roman": "LXII", "date": "2028-02-13",
            "venue": "TBD", "city": "", "network": "TBA",
        }, previous_event=previous)
        self.assertEqual(current["venue"], "Mercedes-Benz Stadium")
        self.assertEqual(current["city"], "Atlanta")
        self.assertEqual(current["network"], "CBS")

    def test_future_super_bowl_real_network_change_is_accepted(self):
        previous = fetch.future_super_bowl_calendar_event({
            "roman": "LXII", "date": "2028-02-13",
            "venue": "Old Venue", "city": "Old City", "network": "CBS",
        })
        current = fetch.future_super_bowl_calendar_event({
            "roman": "LXII", "date": "2028-02-13",
            "venue": "New Venue", "city": "New City", "network": "FOX",
        }, previous_event=previous)
        self.assertEqual(current["network"], "FOX")
        self.assertEqual(current["venue"], "New Venue")

    def test_future_cache_survives_temporary_source_failure(self):
        previous = fetch.future_super_bowl_calendar_event({
            "roman": "LXII", "date": "2028-02-13",
            "venue": "Future Stadium", "city": "Future City", "network": "CBS",
        })
        kept = []
        self.assertEqual(
            fetch.retain_cached_future_super_bowls(kept, [previous], set()), 1)
        self.assertEqual(kept[0]["uid"], previous["uid"])

    def test_espn_temporary_missing_event_is_retained(self):
        prior = recorded_event(date="2027-01-16")
        events = []
        self.assertEqual(
            fetch.retain_temporarily_missing_events(events, [prior], set()), 1)
        self.assertEqual(events[0]["uid"], prior["uid"])

    def test_excluded_giants_cannot_be_reintroduced_by_cache(self):
        prior = recorded_event(id="111", espn_id="111")
        events = []
        self.assertEqual(
            fetch.retain_temporarily_missing_events(events, [prior], {"111"}), 0)
        self.assertEqual(events, [])

    def test_total_espn_wipe_is_rejected(self):
        prior = [recorded_event(id="111", espn_id="111")]
        with self.assertRaises(RuntimeError):
            fetch.validate_espn_result([], prior, 2027, set())

    def test_retention_is_seven_full_calendar_days(self):
        events = [
            recorded_event(id="old", date="2026-10-01"),
            recorded_event(id="boundary", date="2026-10-02"),
            recorded_event(id="future", date="2027-01-16"),
        ]
        kept, dropped = fetch.filter_events_by_retention(events)
        self.assertEqual([x["id"] for x in kept], ["boundary", "future"])
        self.assertEqual(dropped, 1)

    def test_espn_placeholder_and_future_super_bowl_deduplicate(self):
        espn = recorded_event(id="super-bowl-lxi",
                              espn_id="401873270")
        duplicate = fetch.future_super_bowl_calendar_event({
            "roman": "LXI", "date": "2027-02-14",
            "venue": "SoFi Stadium", "city": "Inglewood", "network": "ESPN",
        })
        unique = fetch.deduplicate_events([espn, duplicate])
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["source"], "espn")

    def test_no_change_preserves_dtstamp_and_uid(self):
        prior = recorded_event()
        current = copy.deepcopy(prior)
        fetch.assign_stable_metadata([current], [prior])
        self.assertEqual(current["uid"], prior["uid"])
        self.assertEqual(current["dtstamp"], prior["dtstamp"])

    def test_change_preserves_uid_and_updates_dtstamp(self):
        prior = recorded_event()
        current = copy.deepcopy(prior)
        current["name"] = "Buffalo Bills @ New York Jets"
        fetch.assign_stable_metadata([current], [prior])
        self.assertEqual(current["uid"], prior["uid"])
        self.assertNotEqual(current["dtstamp"], prior["dtstamp"])

    def test_future_date_parser_rejects_tba_and_non_sunday(self):
        self.assertIsNone(fetch.parse_future_date_text("TBA", 2029))
        self.assertIsNone(fetch.parse_future_date_text("February 12, 2029", 2029))
        self.assertEqual(fetch.parse_future_date_text(
            "February 11, 2029", 2029), "2029-02-11")


class CalendarCompatibilityCases(unittest.TestCase):
    def test_checked_in_production_calendar(self):
        self.assertEqual(validate_calendar.validate(), 14)

    def test_roundtrip_ics_parses_in_independent_library(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            events_path = root / "events.json"
            calendar_path = root / "calendar.ics"
            events = [
                recorded_event(name="Wild Card Playoffs"),
                recorded_event(
                    id="401873270", uid="nfl-401873270@nfl-playoff-calendar",
                    name="Baltimore Ravens @ Kansas City Chiefs",
                    date="2027-01-17T21:30:00Z", all_day=False,
                    venue="Long Named NFL Stadium", city="Sample City",
                    network="NBC",
                ),
                recorded_event(
                    id="super-bowl-lxi", uid=fetch.super_bowl_uid("LXI"),
                    name="Super Bowl LXI", date="2027-02-14T23:30:00Z",
                    all_day=False, venue="SoFi Stadium", city="Inglewood",
                    network="ESPN / ABC", streaming="ESPN App / Disney+",
                ),
            ]
            events_path.write_text(json.dumps(events), encoding="utf-8")
            with patch.object(generator, "EVENTS_FILE", events_path), \
                 patch.object(generator, "CALENDAR_FILE", calendar_path):
                generator.main()
            self.assertEqual(validate_calendar.validate(
                events_path, calendar_path), 3)

    def test_unicode_folding_and_text_escaping(self):
        item = recorded_event(
            name="✨ " + "Very Long Team Name " * 10 + ", The Final; Match",
            venue="Stadium, Level 2", city="Town; State")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / "events.json"
            ics = root / "calendar.ics"
            data.write_text(json.dumps([item]), encoding="utf-8")
            with patch.object(generator, "EVENTS_FILE", data), \
                 patch.object(generator, "CALENDAR_FILE", ics):
                generator.main()
            self.assertEqual(validate_calendar.validate(data, ics), 1)
            self.assertIn(b"\r\n ", ics.read_bytes())


if __name__ == "__main__":
    unittest.main()
