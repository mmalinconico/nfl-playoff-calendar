# NFL Playoff Calendar

An automatically updating iCalendar (`.ics`) subscription for the NFL postseason.

Subscribe once, and your calendar stays up to date as playoff matchups, kickoff times, venues, cities, television networks, and other confirmed event details are announced.

## Included Events

- Wild Card Round
- Divisional Round
- AFC Championship Game
- NFC Championship Game
- Super Bowl

New York Giants postseason games are excluded to avoid duplication with the official Giants calendar.

Completed games remain on the calendar for approximately seven days before being removed.

## Subscribe

Use this subscription URL:

https://mmalinconico.github.io/nfl-playoff-calendar/nfl-playoffs.ics

## Features

- Retrieves active NFL postseason schedule information from ESPN.
- Updates every four hours during playoff season, from December through February.
- Checks monthly during the offseason, from March through November.
- Automatically updates matchups, kickoff times, venues, cities, and television networks as information becomes available.
- Includes confirmed Super Bowl streaming information when available.
- Can publish future Super Bowls before ESPN lists them once an exact date has been independently verified.
- Uses stable Super Bowl event IDs so future placeholders can transition cleanly to ESPN data without creating duplicates.
- Retains completed games for seven days.
- Generates a standards-compliant iCalendar (`.ics`) subscription.
- Hosted with GitHub Pages.

## Supported Calendar Apps

- Apple Calendar
- Google Calendar
- Microsoft Outlook
- Any application that supports iCalendar subscriptions

## How It Works

A scheduled GitHub Actions workflow retrieves the latest postseason data, verifies eligible future Super Bowl information, rebuilds the calendar file, and publishes any changes through GitHub Pages.

Active postseason games are sourced from ESPN. Future Super Bowls may be discovered from public sources, but an event is not published until its exact calendar date has been independently verified. Super Bowl streaming information is added only when reliably confirmed and does not affect whether the event is published.

## Data Sources

- ESPN Core API for active postseason schedule data
- Publicly available sources used to discover and verify future Super Bowl details

## Disclaimer

This is an unofficial, fan-created calendar and is not affiliated with the NFL, ESPN, or any other data provider.

Event information is sourced from publicly available data and updated automatically. Playoff schedules, kickoff times, venues, television assignments, streaming availability, and participating teams are subject to change.
