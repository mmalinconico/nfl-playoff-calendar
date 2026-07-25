# NFL Playoff Calendar

An automatically updating iCalendar (`.ics`) subscription for the NFL postseason.

Subscribe once, and your calendar stays up to date as playoff matchups, kickoff times, venues, cities, and television networks are announced.

## Included Events

- Wild Card Round
- Divisional Round
- AFC Championship Game
- NFC Championship Game
- Super Bowl
- Officially dated future Super Bowls

Completed games remain on the calendar for approximately seven days before being removed.

## Subscribe

Use this subscription URL:

https://mmalinconico.github.io/nfl-playoff-calendar/nfl-playoffs.ics

## Features

- Retrieves active NFL postseason schedule information from ESPN.
- Includes future Super Bowls once an exact date has been confirmed by an official source.
- Updates every four hours during playoff season, from December through February.
- Checks monthly during the offseason, from March through November.
- Automatically updates event names, kickoff times, venues, cities, and television networks as information becomes available.
- Retains completed games for seven days.
- Generates a standards-compliant iCalendar (`.ics`) subscription.
- Hosted with GitHub Pages.

## Supported Calendar Apps

- Apple Calendar
- Google Calendar
- Microsoft Outlook
- Any application that supports iCalendar subscriptions

## How It Works

A scheduled GitHub Actions workflow retrieves the latest postseason data, adds officially dated future Super Bowls, rebuilds the calendar file, and publishes any changes through GitHub Pages.

## Data Sources

- ESPN Scoreboard API
- NFL Football Operations
- Official Super Bowl host and stadium sources

## Disclaimer

This is an unofficial, fan-created calendar and is not affiliated with the NFL, ESPN, or any Super Bowl host organization.

Event information is sourced from publicly available data. Playoff schedules, kickoff times, venues, television assignments, and participating teams are subject to change.
