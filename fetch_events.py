import json
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

EVENTS_FILE = Path("data/events.json")
PAST_EVENT_RETENTION_DAYS = 7
CALENDAR_TIMEZONE = ZoneInfo("America/New_York")
POSTSEASON_SEASON_TYPE = 3
POSTSEASON_WEEKS = (1, 2, 3, 4)
GIANTS_ESPN_TEAM_ID = "19"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Deep-future Super Bowls are discovered automatically instead of being
# hard-coded. Wikipedia supplies structured discovery/metadata, but an exact
# calendar date is published only when it is independently corroborated by a
# conservative date source. This prevents inferred future dates from leaking
# into the calendar before they are actually announced.
FUTURE_SUPER_BOWL_LOOKAHEAD_YEARS = 8
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
CBS_FUTURE_SUPER_BOWL_URL = (
    "https://www.cbssports.com/nfl/news/"
    "super-bowl-locations-dates-2027-2028/"
)
NFL_IMPORTANT_DATES_URL = (
    "https://operations.nfl.com/"
    "calendar-events/nfl-important-dates"
)

# Optional streaming metadata is deliberately independent of publication.
# A Super Bowl is published as soon as its event/date passes the normal
# verification rules; streaming can be added later without holding it up.
# Only put a service here when its availability for that Super Bowl is
# reliably confirmed. Do not infer streaming from the TV network.
CONFIRMED_SUPER_BOWL_STREAMING = {
    "LXI": "ESPN App / Disney+",
    "LXII": "Paramount+",
}

# Emergency-only escape hatch. Normal operation should leave this empty.
# If a trusted source changes format and a confirmed future Super Bowl would
# otherwise disappear, an entry can temporarily be added here using:
# {
#     "roman": "LXV",
#     "date": "2031-02-09",
#     "venue": "Example Stadium",
#     "city": "Example City, State",
#     "network": "TBA",
#     "streaming": "Example Streamer",  # optional
#     "source_url": "https://trusted-source.example/...",
# }
MANUAL_FUTURE_SUPER_BOWL_OVERRIDES = []

FUTURE_SUPER_BOWL_SOURCES = {
    "future-super-bowl",
    "official-future-super-bowl",
    "wikipedia-future-super-bowl",
    "manual-future-super-bowl",
}

CALENDAR_FIELDS = (
    "name",
    "date",
    "all_day",
    "venue",
    "city",
    "network",
    "streaming",
    "status",
)


def calendar_today():
    return datetime.now(CALENDAR_TIMEZONE).date()


def normalize_id(value):
    if value is None:
        return ""

    return str(value)


def slugify(value):
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value).lower(),
    ).strip("-")

    return slug or "unknown"


def load_previous_events():
    if not EVENTS_FILE.exists():
        return []

    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return data

    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not load previous events: {error}")

    return []


def parse_event_datetime(date_text):
    if not date_text:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(date_text).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except (TypeError, ValueError):
        return None


def event_calendar_date(event):
    date_text = event.get("date", "")

    if event.get("all_day"):
        try:
            return datetime.strptime(
                date_text,
                "%Y-%m-%d",
            ).date()
        except (TypeError, ValueError):
            return None

    event_datetime = parse_event_datetime(date_text)

    if event_datetime is None:
        return None

    return event_datetime.astimezone(
        CALENDAR_TIMEZONE
    ).date()


def integer_to_roman(number):
    values = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]

    result = []

    for value, numeral in values:
        while number >= value:
            result.append(numeral)
            number -= value

    return "".join(result)


def super_bowl_roman_for_year(postseason_year):
    # Super Bowl I was played in 1967.
    super_bowl_number = postseason_year - 1966

    if super_bowl_number < 1:
        return None

    return integer_to_roman(super_bowl_number)


def super_bowl_event_id(roman):
    return f"super-bowl-{roman.lower()}"


def super_bowl_uid(roman):
    return f"super-bowl-{roman.lower()}@nfl-playoff-calendar"


def confirmed_super_bowl_streaming(roman):
    return normalize_whitespace(
        CONFIRMED_SUPER_BOWL_STREAMING.get(
            str(roman or "").upper(),
            "",
        )
    )


class TableTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = None
        self.current_cell = None
        self.cell_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()

        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = []
            self.cell_depth = 1
        elif self.current_cell is not None:
            self.cell_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()

        if self.current_cell is not None:
            if tag in {"td", "th"} and self.cell_depth == 1:
                cell_text = normalize_whitespace(
                    " ".join(self.current_cell)
                )
                self.current_row.append(cell_text)
                self.current_cell = None
                self.cell_depth = 0
                return

            self.cell_depth = max(0, self.cell_depth - 1)

        if tag == "tr" and self.current_row is not None:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = None

    def handle_data(self, data):
        if self.current_cell is not None:
            cleaned = str(data).strip()
            if cleaned:
                self.current_cell.append(cleaned)


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def get_text(url, label, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    text = response.text

    if not text:
        raise RuntimeError(f"{label} returned an empty response.")

    return text


def month_number(value):
    cleaned = str(value or "").strip().lower().rstrip(".")
    months = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
    }
    return months.get(cleaned)


def parse_future_date_text(value, expected_year):
    text = normalize_whitespace(value)

    if not text or re.search(r"\b(?:TBD|TBA)\b", text, re.I):
        return None

    match = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?)\.?\s+"
        r"(\d{1,2})(?:,?\s+(20\d{2}))?\b",
        text,
        re.I,
    )

    if not match:
        return None

    month = month_number(match.group(1))
    day = int(match.group(2))
    year = int(match.group(3) or expected_year)

    if year != expected_year or month is None:
        return None

    try:
        parsed = date(year, month, day)
    except ValueError:
        return None

    # The Super Bowl is played on Sunday. Treat any other weekday as a bad
    # parse rather than accepting a suspicious deep-future date.
    if parsed.weekday() != 6:
        return None

    return parsed.isoformat()


def parse_wikipedia_venue_city(extract):
    text = normalize_whitespace(extract)
    stadium_terms = (
        "Stadium",
        "Superdome",
        "Dome",
        "Field",
    )
    stadium_pattern = "|".join(
        re.escape(term) for term in stadium_terms
    )
    match = re.search(
        rf"\bat\s+([^.;]+?(?:{stadium_pattern}))\s+in\s+"
        r"([^.;]+?)(?:\.|;|$)",
        text,
        re.I,
    )

    if not match:
        return "", ""

    venue = normalize_whitespace(match.group(1))
    city = normalize_whitespace(match.group(2)).rstrip(",")
    return venue, city


def parse_wikipedia_network(extract):
    text = normalize_whitespace(extract)
    match = re.search(
        r"\b(?:televised|broadcast)(?: nationally)? by "
        r"(?:both )?(.+?)(?:\.| as part of |, with | and will )",
        text,
        re.I,
    )

    if not match:
        return "TBA"

    network = normalize_whitespace(match.group(1))
    network = re.sub(r"\s+and\s+", " / ", network, flags=re.I)

    if len(network) > 80:
        return "TBA"

    return network


def wikipedia_future_super_bowl_candidates():
    today = calendar_today()
    first_year = today.year

    # Once the current year's Super Bowl has passed, begin with next year.
    current_roman = super_bowl_roman_for_year(first_year)
    current_event_id = (
        super_bowl_event_id(current_roman)
        if current_roman
        else ""
    )

    previous_events = load_previous_events()
    current_event = next(
        (
            event
            for event in previous_events
            if normalize_id(event.get("id")) == current_event_id
        ),
        None,
    )

    if (
        current_event is not None
        and (event_calendar_date(current_event) or date.min) < today
    ):
        first_year += 1

    years = range(
        first_year,
        first_year + FUTURE_SUPER_BOWL_LOOKAHEAD_YEARS + 1,
    )
    title_to_year = {}

    for super_bowl_year in years:
        roman = super_bowl_roman_for_year(super_bowl_year)
        if roman:
            title_to_year[f"Super Bowl {roman}"] = super_bowl_year

    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "extracts",
        "exintro": 1,
        "explaintext": 1,
        "redirects": 1,
        "titles": "|".join(title_to_year),
    }
    response = requests.get(
        WIKIPEDIA_API_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    pages = data.get("query", {}).get("pages", [])

    if not isinstance(pages, list):
        raise RuntimeError(
            "Wikipedia future Super Bowl lookup returned an unexpected response."
        )

    candidates = []

    for page in pages:
        if not isinstance(page, dict) or page.get("missing"):
            continue

        title = normalize_whitespace(page.get("title"))
        expected_year = title_to_year.get(title)

        if expected_year is None:
            continue

        roman_match = re.fullmatch(r"Super Bowl ([IVXLCDM]+)", title)
        if not roman_match:
            continue

        roman = roman_match.group(1)
        extract = str(page.get("extract", ""))
        venue, city = parse_wikipedia_venue_city(extract)

        candidates.append({
            "roman": roman,
            "year": expected_year,
            "wikipedia_date": parse_future_date_text(
                extract,
                expected_year,
            ),
            "venue": venue,
            "city": city,
            "network": parse_wikipedia_network(extract),
            "discovery_source_url": (
                "https://en.wikipedia.org/wiki/"
                f"Super_Bowl_{roman}"
            ),
        })

    return candidates


def cbs_verified_future_dates(candidates):
    html = get_text(
        CBS_FUTURE_SUPER_BOWL_URL,
        "CBS Sports future Super Bowl page",
    )
    parser = TableTextParser()
    parser.feed(html)
    verified = {}
    observed = set()

    for candidate in candidates:
        roman = candidate["roman"]
        expected_year = candidate["year"]

        for row in parser.rows:
            row_text = " | ".join(row)

            if not re.search(
                rf"(?<![A-Z]){re.escape(roman)}(?![A-Z])",
                row_text,
                re.I,
            ):
                continue

            if str(expected_year) not in row_text:
                continue

            observed.add(roman)
            parsed_date = None

            for cell in row:
                parsed_date = parse_future_date_text(
                    cell,
                    expected_year,
                )
                if parsed_date:
                    break

            if parsed_date:
                verified[roman] = parsed_date
                break

    # Fallback for article markup that does not expose semantic table cells.
    # It remains conservative: the Roman numeral, year and exact date must all
    # occur in a short local window. TBD/TBA rows produce no date.
    plain = normalize_whitespace(re.sub(r"<[^>]+>", " ", html))

    for candidate in candidates:
        roman = candidate["roman"]

        if roman in verified:
            continue

        expected_year = candidate["year"]
        matches = list(
            re.finditer(
                rf"(?<![A-Z]){re.escape(roman)}(?![A-Z])",
                plain,
                re.I,
            )
        )

        for match in matches:
            window = plain[
                match.start():match.start() + 260
            ]

            if str(expected_year) not in window:
                continue

            observed.add(roman)

            if re.search(r"\b(?:TBD|TBA)\b", window, re.I):
                continue

            parsed_date = parse_future_date_text(
                window,
                expected_year,
            )

            if parsed_date:
                verified[roman] = parsed_date
                break

    return verified, observed


def nfl_operations_verified_future_dates(candidates):
    html = get_text(
        NFL_IMPORTANT_DATES_URL,
        "NFL Football Operations important dates",
    )
    plain = normalize_whitespace(re.sub(r"<[^>]+>", " ", html))
    verified = {}

    for candidate in candidates:
        roman = candidate["roman"]
        expected_year = candidate["year"]
        pattern = re.compile(
            rf"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?)\.?\s+"
            rf"(\d{{1,2}}).{{0,180}}Super Bowl\s+{re.escape(roman)}",
            re.I,
        )
        match = pattern.search(plain)

        if not match:
            continue

        parsed_date = parse_future_date_text(
            f"{match.group(1)} {match.group(2)} {expected_year}",
            expected_year,
        )

        if parsed_date:
            verified[roman] = parsed_date

    return verified


def discover_verified_future_super_bowls(previous_events):
    try:
        candidates = wikipedia_future_super_bowl_candidates()
        wikipedia_ok = True
    except (requests.RequestException, ValueError, RuntimeError) as error:
        print(f"Future Super Bowl discovery unavailable: {error}")
        candidates = []
        wikipedia_ok = False

    cbs_dates = {}
    cbs_observed = set()
    cbs_ok = False

    if candidates:
        try:
            cbs_dates, cbs_observed = cbs_verified_future_dates(
                candidates
            )
            cbs_ok = bool(cbs_observed)

            if not cbs_ok:
                print(
                    "CBS future Super Bowl page was reachable but its "
                    "future-Super-Bowl table could not be parsed."
                )
        except (requests.RequestException, RuntimeError) as error:
            print(f"CBS future Super Bowl verification unavailable: {error}")

    nfl_dates = {}
    nfl_ok = False

    if candidates:
        try:
            nfl_dates = nfl_operations_verified_future_dates(
                candidates
            )
            nfl_ok = True
        except (requests.RequestException, RuntimeError) as error:
            print(f"NFL Operations date verification unavailable: {error}")

    verified_events = []

    for candidate in candidates:
        roman = candidate["roman"]
        cbs_date = cbs_dates.get(roman)
        nfl_date = nfl_dates.get(roman)
        dates = {
            value
            for value in (cbs_date, nfl_date)
            if value
        }

        if len(dates) > 1:
            print(
                f"Skipped Super Bowl {roman}: trusted sources disagree "
                f"on date ({sorted(dates)})."
            )
            continue

        verified_date = next(iter(dates), None)

        if not verified_date:
            wiki_date = candidate.get("wikipedia_date")
            if wiki_date:
                print(
                    f"Discovered Super Bowl {roman} with Wikipedia date "
                    f"{wiki_date}, but no independent exact-date "
                    "confirmation; not publishing yet."
                )
            else:
                print(
                    f"Discovered Super Bowl {roman}, but exact date is "
                    "not confirmed; not publishing yet."
                )
            continue

        if candidate.get("wikipedia_date") not in {None, verified_date}:
            print(
                f"Skipped Super Bowl {roman}: Wikipedia date "
                f"{candidate.get('wikipedia_date')} conflicts with "
                f"verified date {verified_date}."
            )
            continue

        if not candidate.get("venue") or not candidate.get("city"):
            print(
                f"Skipped Super Bowl {roman}: venue/city could not be "
                "parsed from discovery source."
            )
            continue

        source_url = (
            NFL_IMPORTANT_DATES_URL
            if nfl_date == verified_date
            else CBS_FUTURE_SUPER_BOWL_URL
        )

        verified_events.append({
            "roman": roman,
            "date": verified_date,
            "venue": candidate["venue"],
            "city": candidate["city"],
            "network": candidate.get("network") or "TBA",
            "streaming": confirmed_super_bowl_streaming(roman),
            "source_url": source_url,
        })

    # Emergency manual entries override discovered values by Roman numeral.
    by_roman = {
        item["roman"]: item
        for item in verified_events
    }

    for override in MANUAL_FUTURE_SUPER_BOWL_OVERRIDES:
        roman = normalize_whitespace(override.get("roman")).upper()
        date_text = normalize_whitespace(override.get("date"))

        try:
            parsed_date = datetime.strptime(
                date_text,
                "%Y-%m-%d",
            ).date()
        except (TypeError, ValueError):
            raise RuntimeError(
                f"Invalid manual future Super Bowl date: {override}"
            )

        expected_roman = super_bowl_roman_for_year(
            parsed_date.year
        )

        if roman != expected_roman or parsed_date.weekday() != 6:
            raise RuntimeError(
                f"Invalid manual future Super Bowl override: {override}"
            )

        by_roman[roman] = {
            "roman": roman,
            "date": date_text,
            "venue": normalize_whitespace(override.get("venue")),
            "city": normalize_whitespace(override.get("city")),
            "network": normalize_whitespace(
                override.get("network") or "TBA"
            ),
            "streaming": normalize_whitespace(
                override.get("streaming")
                or confirmed_super_bowl_streaming(roman)
            ),
            "source_url": normalize_whitespace(
                override.get("source_url")
            ),
            "manual": True,
        }

    source_degraded = not wikipedia_ok or not cbs_ok

    # If a previously verified future placeholder is not reproduced, retain
    # it only when the sources appear degraded. Do not call the source
    # degraded when CBS explicitly sees that Super Bowl but currently shows
    # no exact date (for example, a row marked TBD).
    verified_romans = set(by_roman)
    candidate_romans = {item["roman"] for item in candidates}

    for previous in previous_events:
        if previous.get("source") not in FUTURE_SUPER_BOWL_SOURCES:
            continue

        previous_date = event_calendar_date(previous)
        if previous_date is None or previous_date < calendar_today():
            continue

        event_id = normalize_id(previous.get("id"))
        match = re.fullmatch(r"super-bowl-([ivxlcdm]+)", event_id, re.I)

        if not match:
            continue

        roman = match.group(1).upper()

        if roman in verified_romans:
            continue

        if roman in cbs_observed and roman not in cbs_dates and roman not in nfl_dates:
            # The verifier explicitly has this game but no exact date.
            continue

        if roman not in candidate_romans or roman not in verified_romans:
            source_degraded = True

    return list(by_roman.values()), source_degraded, nfl_ok


def future_super_bowl_calendar_event(super_bowl):
    roman = super_bowl["roman"]
    event = {
        "id": super_bowl_event_id(roman),
        "uid": super_bowl_uid(roman),
        "name": f"Super Bowl {roman}",
        "date": super_bowl["date"],
        "venue": super_bowl["venue"],
        "city": super_bowl["city"],
        "network": super_bowl.get("network", "TBA"),
        "promotion": "NFL",
        "all_day": True,
        "status": "Kickoff time TBA",
        "source": (
            "manual-future-super-bowl"
            if super_bowl.get("manual")
            else "future-super-bowl"
        ),
        "source_url": super_bowl.get("source_url", ""),
    }

    streaming = normalize_whitespace(
        super_bowl.get("streaming")
        or confirmed_super_bowl_streaming(roman)
    )

    if streaming:
        event["streaming"] = streaming

    return event


def retain_cached_future_super_bowls(
    events,
    previous_events,
    excluded_event_ids,
):
    current_ids = {
        normalize_id(event.get("id"))
        for event in events
    }
    retained = 0

    for previous in previous_events:
        if previous.get("source") not in FUTURE_SUPER_BOWL_SOURCES:
            continue

        event_id = normalize_id(previous.get("id"))

        if not event_id or event_id in current_ids:
            continue

        if event_id in excluded_event_ids:
            continue

        previous_date = event_calendar_date(previous)

        if previous_date is None or previous_date < calendar_today():
            continue

        events.append(dict(previous))
        current_ids.add(event_id)
        retained += 1

    return retained


def event_labels(event, competition):
    labels = [
        event.get("name", ""),
        event.get("shortName", ""),
        competition.get("name", ""),
        competition.get("shortName", ""),
    ]

    status = event.get("status", {})

    if isinstance(status, dict):
        status_type = status.get("type", {})

        if isinstance(status_type, dict):
            labels.extend([
                status_type.get("description", ""),
                status_type.get("detail", ""),
                status_type.get("shortDetail", ""),
            ])

    for note in competition.get("notes", []):
        if isinstance(note, dict):
            labels.append(note.get("headline", ""))

    return [
        str(label).strip()
        for label in labels
        if label
    ]


def ref_resource_id(ref, resource):
    match = re.search(
        rf"/{re.escape(resource)}/([^/?]+)",
        str(ref or ""),
    )

    if match:
        return normalize_id(match.group(1))

    return ""


def competition_team_ids(competition):
    team_ids = set()
    competitors = competition.get("competitors", [])

    if not isinstance(competitors, list):
        return team_ids

    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue

        competitor_id = normalize_id(competitor.get("id"))

        if competitor_id:
            team_ids.add(competitor_id)

        competitor_ref_id = ref_resource_id(
            competitor.get("$ref"),
            "competitors",
        )

        if competitor_ref_id:
            team_ids.add(competitor_ref_id)

        team = competitor.get("team")

        if not isinstance(team, dict):
            continue

        team_id = normalize_id(team.get("id"))

        if team_id:
            team_ids.add(team_id)

        team_ref_id = ref_resource_id(
            team.get("$ref"),
            "teams",
        )

        if team_ref_id:
            team_ids.add(team_ref_id)

    return team_ids


def label_mentions_giants(value):
    text = str(value or "").strip().lower()

    if not text:
        return False

    if "new york giants" in text or "ny giants" in text:
        return True

    return re.search(
        r"(?<![a-z0-9])nyg(?![a-z0-9])",
        text,
    ) is not None


def event_involves_giants(event, competition):
    if GIANTS_ESPN_TEAM_ID in competition_team_ids(competition):
        return True

    return any(
        label_mentions_giants(label)
        for label in event_labels(event, competition)
    )


def stored_event_involves_giants(event):
    return label_mentions_giants(event.get("name", ""))


def is_super_bowl_event(event, competition):
    return any(
        "super bowl" in label.lower()
        for label in event_labels(event, competition)
    )


def is_postseason_event(event, competition):
    labels = " ".join(
        event_labels(event, competition)
    ).lower()

    if "pro bowl" in labels:
        return False

    season = event.get("season", {})
    season_type = season.get("type") if isinstance(season, dict) else None
    season_slug = (
        str(season.get("slug", "")).lower()
        if isinstance(season, dict)
        else ""
    )

    if season_type == 3 or "post" in season_slug:
        return True

    postseason_terms = (
        "wild card",
        "divisional",
        "afc championship",
        "nfc championship",
        "conference championship",
        "super bowl",
        "playoff",
    )

    return any(term in labels for term in postseason_terms)


def network_names(competition):
    names = []

    for broadcast in competition.get("broadcasts", []):
        if not isinstance(broadcast, dict):
            continue

        for name in broadcast.get("names", []):
            cleaned = str(name).strip()

            if cleaned and cleaned not in names:
                names.append(cleaned)

    return " / ".join(names)


def is_placeholder_time(event_datetime, competition):
    if event_datetime is None:
        return False

    if competition.get("timeValid") is False:
        return True

    local_datetime = event_datetime.astimezone(
        CALENDAR_TIMEZONE
    )

    # ESPN commonly uses midnight Eastern when a date is known but
    # a kickoff time has not been announced. NFL playoff games do not
    # actually begin at midnight Eastern.
    return (
        local_datetime.hour == 0
        and local_datetime.minute == 0
        and local_datetime.second == 0
    )


def core_get_json(url, params=None, label="ESPN Core API"):
    response = requests.get(
        str(url).replace("http://", "https://"),
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as error:
        raise RuntimeError(
            f"{label} returned invalid JSON."
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{label} returned an unexpected response."
        )

    return data


def core_collection_items(url, params=None, label="ESPN Core API"):
    data = core_get_json(
        url,
        params=params,
        label=label,
    )

    items = data.get("items")

    if not isinstance(items, list):
        raise RuntimeError(
            f"{label} response is missing an items list."
        )

    return items


def resolve_ref(value, label):
    if not isinstance(value, dict):
        return {}

    ref = value.get("$ref")

    if not ref:
        return value

    return core_get_json(ref, label=label)


def core_event_id_from_ref(item):
    if not isinstance(item, dict):
        return ""

    event_id = normalize_id(item.get("id"))

    if event_id:
        return event_id

    ref = str(item.get("$ref", ""))
    match = re.search(r"/events/([^/?]+)", ref)

    if match:
        return normalize_id(match.group(1))

    return ""


def previous_event_for_espn_id(previous_events, espn_id):
    espn_id = normalize_id(espn_id)

    for event in previous_events:
        previous_id = normalize_id(event.get("id"))
        previous_espn_id = normalize_id(
            event.get("espn_id")
            or (
                previous_id
                if previous_id.isdigit()
                else ""
            )
        )

        if previous_espn_id == espn_id:
            return event

    return None


def previous_event_for_id(previous_events, event_id):
    event_id = normalize_id(event_id)

    if not event_id:
        return None

    for event in previous_events:
        if normalize_id(event.get("id")) == event_id:
            return event

    return None


def metadata_is_missing(value):
    normalized = normalize_whitespace(value).casefold()

    return normalized in {
        "",
        "tba",
        "tbd",
        "to be announced",
        "to be determined",
    }


def fetch_core_postseason_event_refs(season_year):
    base = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/seasons/"
        f"{season_year}/types/{POSTSEASON_SEASON_TYPE}/weeks"
    )

    collected = []
    seen_ids = set()

    for week in POSTSEASON_WEEKS:
        url = f"{base}/{week}/events"
        items = core_collection_items(
            url,
            params={"limit": 100},
            label=f"ESPN Core postseason week {week}",
        )

        print(
            f"ESPN Core postseason week {week}: "
            f"{len(items)} event references"
        )

        for item in items:
            event_id = core_event_id_from_ref(item)

            if not event_id or event_id in seen_ids:
                continue

            collected.append({
                "week": week,
                "id": event_id,
                "$ref": item.get(
                    "$ref",
                    (
                        "https://sports.core.api.espn.com/v2/"
                        "sports/football/leagues/nfl/events/"
                        f"{event_id}"
                    ),
                ),
            })
            seen_ids.add(event_id)

    return collected


def core_competition_for_event(event_id):
    url = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/events/"
        f"{event_id}/competitions/{event_id}"
    )

    return core_get_json(
        url,
        label=f"ESPN Core competition {event_id}",
    )


def core_broadcast_networks(event_id):
    url = (
        "https://sports.core.api.espn.com/v2/"
        "sports/football/leagues/nfl/events/"
        f"{event_id}/competitions/{event_id}/broadcasts"
    )

    try:
        items = core_collection_items(
            url,
            params={"limit": 100},
            label=f"ESPN Core broadcasts {event_id}",
        )
    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status == 404:
            return ""

        raise

    names = []

    for item in items:
        broadcast = resolve_ref(
            item,
            f"ESPN Core broadcast {event_id}",
        )

        candidates = []

        if isinstance(broadcast.get("names"), list):
            candidates.extend(broadcast["names"])

        for key in (
            "name",
            "shortName",
            "displayName",
            "shortDisplayName",
        ):
            if broadcast.get(key):
                candidates.append(broadcast[key])

        media = broadcast.get("media")

        if isinstance(media, dict):
            for key in (
                "shortName",
                "name",
                "displayName",
            ):
                if media.get(key):
                    candidates.append(media[key])

        for candidate in candidates:
            cleaned = str(candidate).strip()

            if cleaned and cleaned not in names:
                names.append(cleaned)

    return " / ".join(names)


def core_venue_details(competition):
    venue_value = competition.get("venue")

    if not isinstance(venue_value, dict):
        return "", ""

    try:
        venue = resolve_ref(
            venue_value,
            "ESPN Core venue",
        )
    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status == 404:
            venue = venue_value
        else:
            raise

    venue_name = str(
        venue.get("fullName")
        or venue.get("name")
        or ""
    ).strip()

    city = ""
    address = venue.get("address")

    if isinstance(address, dict):
        city = str(
            address.get("city")
            or address.get("summary")
            or ""
        ).strip()

    return venue_name, city


def core_placeholder_time(
    event_datetime,
    event_detail,
    competition,
):
    if event_datetime is None:
        return False

    for source in (competition, event_detail):
        if source.get("timeValid") is False:
            return True

    local_datetime = event_datetime.astimezone(
        CALENDAR_TIMEZONE
    )

    return (
        local_datetime.hour == 0
        and local_datetime.minute == 0
        and local_datetime.second == 0
    )


def sensible_core_name(
    event_detail,
    previous_event,
    week,
    current_super_bowl_roman,
):
    candidates = [
        event_detail.get("name", ""),
        event_detail.get("shortName", ""),
    ]

    for candidate in candidates:
        cleaned = str(candidate).strip()

        if cleaned and cleaned.lower() not in {
            "tbd at tbd",
            "tbd @ tbd",
            "tbd vs tbd",
            "tbd",
        }:
            return cleaned

    previous_name = (
        str(previous_event.get("name", "")).strip()
        if previous_event
        else ""
    )

    if previous_name and previous_name.lower() not in {
        "tbd at tbd",
        "tbd @ tbd",
        "tbd vs tbd",
        "tbd",
    }:
        return previous_name

    previous_uid = (
        str(previous_event.get("uid", "")).lower()
        if previous_event
        else ""
    )

    if week == 1:
        return "Wild Card Playoffs"

    if week == 2:
        return "Divisional Playoffs"

    if week == 3:
        if "nfc-championship" in previous_uid:
            return "NFC Championship"

        if "afc-championship" in previous_uid:
            return "AFC Championship"

        return "Conference Championship"

    if week == 4 and current_super_bowl_roman:
        return f"Super Bowl {current_super_bowl_roman}"

    return "NFL Playoff Game"


def fetch_core_postseason_events(
    season_year,
    previous_events,
    current_super_bowl_roman,
):
    event_refs = fetch_core_postseason_event_refs(
        season_year
    )
    events = []
    excluded_espn_ids = set()
    excluded_event_ids = set()

    for item in event_refs:
        espn_event_id = item["id"]
        week = item["week"]
        event_detail = core_get_json(
            item["$ref"],
            label=f"ESPN Core event {espn_event_id}",
        )
        competition = core_competition_for_event(
            espn_event_id
        )
        previous = previous_event_for_espn_id(
            previous_events,
            espn_event_id,
        )

        date_text = str(
            event_detail.get("date")
            or competition.get("date")
            or ""
        )
        event_datetime = parse_event_datetime(
            date_text
        )

        if event_datetime is None:
            raise RuntimeError(
                "ESPN Core event has an invalid date: "
                f"{espn_event_id}"
            )

        local_date = event_datetime.astimezone(
            CALENDAR_TIMEZONE
        ).date().isoformat()

        is_super_bowl = (
            week == 4
            or is_super_bowl_event(event_detail, competition)
        )

        event_id = espn_event_id
        event_uid = ""

        if is_super_bowl and current_super_bowl_roman:
            event_id = super_bowl_event_id(
                current_super_bowl_roman
            )
            event_uid = super_bowl_uid(
                current_super_bowl_roman
            )

            # The future placeholder has the canonical Super Bowl ID but no
            # ESPN ID yet. Once ESPN takes over, use that prior event as a
            # metadata fallback so optional fields such as streaming survive
            # the handoff cleanly.
            if previous is None:
                previous = previous_event_for_id(
                    previous_events,
                    event_id,
                )

        if event_involves_giants(event_detail, competition):
            excluded_espn_ids.add(espn_event_id)
            excluded_event_ids.add(event_id)
            print(
                "Excluded Giants postseason event: "
                f"{espn_event_id}"
            )
            continue

        venue, city = core_venue_details(
            competition
        )
        network = core_broadcast_networks(
            espn_event_id
        )
        streaming = ""

        if is_super_bowl and current_super_bowl_roman:
            streaming = confirmed_super_bowl_streaming(
                current_super_bowl_roman
            )

        if previous is not None:
            if metadata_is_missing(venue):
                venue = previous.get("venue", "")

            if metadata_is_missing(city):
                city = previous.get("city", "")

            if metadata_is_missing(network):
                network = previous.get("network", "")

            if is_super_bowl and not streaming:
                streaming = normalize_whitespace(
                    previous.get("streaming")
                )

        all_day = core_placeholder_time(
            event_datetime,
            event_detail,
            competition,
        )

        if all_day:
            stored_date = local_date
        else:
            stored_date = date_text

        name = sensible_core_name(
            event_detail,
            previous,
            week,
            current_super_bowl_roman,
        )

        calendar_event = {
            "id": event_id,
            "name": name,
            "date": stored_date,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL",
            "source": "espn",
            "espn_id": espn_event_id,
        }

        if is_super_bowl and streaming:
            calendar_event["streaming"] = streaming

        if all_day:
            calendar_event["all_day"] = True
            calendar_event["status"] = (
                "Kickoff time TBA"
            )

        if event_uid:
            calendar_event["uid"] = event_uid

        events.append(calendar_event)

    return events, excluded_espn_ids, excluded_event_ids


def legacy_uid_for_event(event):
    if event.get("uid"):
        return event["uid"]

    if str(event.get("id", "")).startswith("super-bowl-"):
        roman = str(event["id"]).removeprefix(
            "super-bowl-"
        )
        return super_bowl_uid(roman)

    return (
        f"{slugify(event.get('name', 'NFL Playoff Game'))}-"
        f"{normalize_id(event.get('id'))}"
    )


def new_uid_for_event(event):
    if event.get("uid"):
        return event["uid"]

    event_id = normalize_id(event.get("id"))

    if event_id.startswith("super-bowl-"):
        roman = event_id.removeprefix("super-bowl-")
        return super_bowl_uid(roman)

    espn_id = normalize_id(
        event.get("espn_id") or event_id
    )

    return f"nfl-{espn_id}@nfl-playoff-calendar"


def calendar_data_changed(current_event, previous_event):
    return any(
        current_event.get(field, "")
        != previous_event.get(field, "")
        for field in CALENDAR_FIELDS
    )


def previous_event_indexes(previous_events):
    by_id = {}
    by_espn_id = {}

    for event in previous_events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(
            event.get("espn_id")
            or (
                event_id
                if event_id.isdigit()
                else ""
            )
        )

        if event_id:
            by_id[event_id] = event

        if espn_id:
            by_espn_id[espn_id] = event

    return by_id, by_espn_id


def apply_confirmed_super_bowl_streaming(events):
    updated_count = 0

    for event in events:
        event_id = normalize_id(event.get("id"))

        if not event_id.startswith("super-bowl-"):
            continue

        roman = event_id.removeprefix("super-bowl-").upper()
        streaming = confirmed_super_bowl_streaming(roman)

        if not streaming:
            continue

        if event.get("streaming") == streaming:
            continue

        event["streaming"] = streaming
        updated_count += 1

    return updated_count


def assign_stable_metadata(events, previous_events):
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    by_id, by_espn_id = previous_event_indexes(
        previous_events
    )

    for event in events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(event.get("espn_id"))

        previous = by_id.get(event_id)

        if previous is None and espn_id:
            previous = by_espn_id.get(espn_id)

        if previous is not None:
            event["uid"] = (
                previous.get("uid")
                or legacy_uid_for_event(previous)
            )

            if (
                previous.get("dtstamp")
                and not calendar_data_changed(event, previous)
            ):
                event["dtstamp"] = previous["dtstamp"]
            else:
                event["dtstamp"] = timestamp
        else:
            event["uid"] = new_uid_for_event(event)
            event["dtstamp"] = timestamp


def validate_espn_result(
    events,
    previous_events,
    postseason_year,
    excluded_espn_ids,
):
    previous_future = [
        event
        for event in previous_events
        if event.get("source") == "espn"
        and not stored_event_involves_giants(event)
        and normalize_id(
            event.get("espn_id")
            or (
                event.get("id")
                if normalize_id(event.get("id")).isdigit()
                else ""
            )
        ) not in excluded_espn_ids
        and (
            event_calendar_date(event) or date.min
        ) >= calendar_today()
        and str(postseason_year) in event.get("date", "")
    ]

    parsed_future = [
        event
        for event in events
        if event.get("source") == "espn"
        and (
            event_calendar_date(event) or date.min
        ) >= calendar_today()
    ]

    if previous_future and not parsed_future:
        raise RuntimeError(
            "ESPN returned no future postseason events while "
            f"{len(previous_future)} were previously stored. "
            "Aborting to prevent an accidental calendar wipe."
        )


def deduplicate_events(events):
    unique = []
    seen_ids = set()
    seen_espn_ids = set()

    for event in events:
        event_id = normalize_id(event.get("id"))
        espn_id = normalize_id(event.get("espn_id"))

        if not event_id:
            continue

        if event_id in seen_ids:
            continue

        if espn_id and espn_id in seen_espn_ids:
            continue

        unique.append(event)
        seen_ids.add(event_id)

        if espn_id:
            seen_espn_ids.add(espn_id)

    return unique


def filter_events_by_retention(events):
    retention_start = calendar_today() - timedelta(
        days=PAST_EVENT_RETENTION_DAYS
    )
    kept = []
    removed_count = 0

    for event in events:
        event_date = event_calendar_date(event)

        if event_date is None:
            raise RuntimeError(
                "Invalid event date for "
                f"{event.get('name', 'unknown event')}: "
                f"{event.get('date', '')}"
            )

        if event_date < retention_start:
            removed_count += 1
            continue

        kept.append(event)

    return kept, removed_count


def retain_temporarily_missing_events(
    events,
    previous_events,
    excluded_espn_ids,
):
    retention_start = calendar_today() - timedelta(
        days=PAST_EVENT_RETENTION_DAYS
    )
    current_ids = {
        normalize_id(event.get("id"))
        for event in events
    }
    current_espn_ids = {
        normalize_id(event.get("espn_id"))
        for event in events
        if event.get("espn_id")
    }
    retained_count = 0

    for previous in previous_events:
        if previous.get("source") != "espn":
            continue

        if stored_event_involves_giants(previous):
            continue

        event_id = normalize_id(previous.get("id"))
        espn_id = normalize_id(
            previous.get("espn_id")
            or (
                event_id
                if event_id.isdigit()
                else ""
            )
        )

        if espn_id and espn_id in excluded_espn_ids:
            continue

        if event_id in current_ids:
            continue

        if espn_id and espn_id in current_espn_ids:
            continue

        previous_date = event_calendar_date(previous)

        if previous_date is None:
            continue

        if previous_date < retention_start:
            continue

        events.append(dict(previous))
        current_ids.add(event_id)

        if espn_id:
            current_espn_ids.add(espn_id)

        retained_count += 1

    return retained_count


def write_events_atomically(events):
    EVENTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_file = EVENTS_FILE.with_suffix(
        ".json.tmp"
    )

    with temporary_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            events,
            file,
            indent=2,
            ensure_ascii=False,
        )
        file.write("\n")

    temporary_file.replace(EVENTS_FILE)


def main():
    now = datetime.now(CALENDAR_TIMEZONE)
    current_year = now.year

    # Keep following the prior NFL season through March. This avoids
    # assuming the postseason must always end in February.
    if now.month <= 3:
        season_year = current_year - 1
    else:
        season_year = current_year

    postseason_year = season_year + 1
    current_super_bowl_roman = super_bowl_roman_for_year(
        postseason_year
    )

    print(f"Using postseason for NFL season {season_year}")
    print(
        "Searching January-March "
        f"{postseason_year}"
    )

    previous_events = load_previous_events()
    (
        events,
        excluded_espn_ids,
        excluded_event_ids,
    ) = fetch_core_postseason_events(
        season_year,
        previous_events,
        current_super_bowl_roman,
    )

    events = deduplicate_events(events)
    validate_espn_result(
        events,
        previous_events,
        postseason_year,
        excluded_espn_ids,
    )

    retained_count = retain_temporarily_missing_events(
        events,
        previous_events,
        excluded_espn_ids,
    )

    placeholder_count = 0
    cached_future_count = 0
    future_super_bowls, future_source_degraded, _ = (
        discover_verified_future_super_bowls(previous_events)
    )

    for super_bowl in future_super_bowls:
        roman = super_bowl["roman"]
        event_id = super_bowl_event_id(roman)

        if event_id in excluded_event_ids:
            continue

        if any(
            event.get("id") == event_id
            for event in events
        ):
            continue

        event_date = datetime.strptime(
            super_bowl["date"],
            "%Y-%m-%d",
        ).date()

        if event_date < calendar_today():
            continue

        events.append(
            future_super_bowl_calendar_event(super_bowl)
        )
        placeholder_count += 1

    if future_source_degraded:
        cached_future_count = retain_cached_future_super_bowls(
            events,
            previous_events,
            excluded_event_ids,
        )

    events = deduplicate_events(events)
    events, removed_count = filter_events_by_retention(
        events
    )
    streaming_update_count = apply_confirmed_super_bowl_streaming(
        events
    )
    assign_stable_metadata(
        events,
        previous_events,
    )

    events.sort(
        key=lambda event: (
            event_calendar_date(event) or date.max,
            event.get("date", ""),
            event.get("id", ""),
        )
    )

    write_events_atomically(events)

    print(f"Excluded {len(excluded_espn_ids)} Giants postseason events")
    print(f"Retained {retained_count} temporarily missing ESPN events")
    print(f"Retained {cached_future_count} cached future Super Bowls")
    print(f"Filtered {removed_count} events outside retention")
    print(f"Added {placeholder_count} verified future Super Bowls")
    print(f"Applied streaming metadata to {streaming_update_count} Super Bowls")
    print(f"Generated {len(events)} events")


if __name__ == "__main__":
    main()