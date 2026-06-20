import json
import requests

events = []

date_ranges = [
    "20270113-20270119",
    "20270120-20270126",
    "20270127-20270202",
    "20270210-20270216"
]

for date_range in date_ranges:

    url = (
        "https://site.api.espn.com/apis/site/v2/"
        f"sports/football/nfl/scoreboard?dates={date_range}"
    )

    response = requests.get(url)
    response.raise_for_status()

    data = response.json()

    for event in data.get("events", []):

        date = event.get("date")

        competitions = event.get("competitions", [{}])
        competition = competitions[0]

        # Use playoff round name when teams are TBD
        name = event.get("name", "NFL Playoff Game")

        notes = competition.get("notes", [])

        if (
            name == "TBD at TBD"
            and notes
            and "headline" in notes[0]
        ):
            name = notes[0]["headline"]

        venue = (
            competition.get("venue", {})
            .get("fullName", "")
        )

        city = (
            competition.get("venue", {})
            .get("address", {})
            .get("city", "")
        )

        broadcasts = event.get("broadcasts", [])
        network = ""

        if broadcasts:
            network = broadcasts[0].get("names", [""])[0]

        events.append({
            "name": name,
            "date": date,
            "venue": venue,
            "city": city,
            "network": network,
            "promotion": "NFL"
        })

events.sort(key=lambda x: x["date"])

with open("data/events.json", "w") as f:
    json.dump(events, f, indent=2)

print(f"Generated {len(events)} events")
