# NFL Playoff Calendar

An automatically updating iCalendar (`.ics`) subscription for the NFL postseason.

Subscribe once, and your calendar stays up to date as playoff matchups, kickoff times, venues, cities, and television networks are announced.

## Included Events

- Wild Card Round
- Divisional Round
- AFC Championship Game
- NFC Championship Game
- Super Bowl

Completed games remain on the calendar for approximately seven days before being removed.

## Subscribe

Use this subscription URL:

https://mmalinconico.github.io/nfl-playoff-calendar/nfl-playoffs.ics

## Features

- Retrieves NFL postseason schedule information from ESPN.
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

A scheduled GitHub Actions workflow retrieves the latest postseason data, rebuilds the calendar file, and publishes any changes through GitHub Pages.

## Data Source

- ESPN Scoreboard API

## Disclaimer

This is an unofficial, fan-created calendar and is not affiliated with the NFL or ESPN.

Event information is sourced from publicly available data and updated automatically. Playoff schedules, kickoff times, venues, television assignments, and participating teams are subject to change.
