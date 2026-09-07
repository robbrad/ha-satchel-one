# Satchel One for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate HACS](https://github.com/robbrad/ha-satchel-one/actions/workflows/hacs_validation.yml/badge.svg)](https://github.com/robbrad/ha-satchel-one/actions/workflows/hacs_validation.yml)
[![Tests](https://github.com/robbrad/ha-satchel-one/actions/workflows/tests.yml/badge.svg)](https://github.com/robbrad/ha-satchel-one/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Bring your child's **Satchel One** (formerly Show My Homework) account into
Home Assistant: outstanding homework, what is overdue, what is due next,
detentions and behaviour points.

> Unofficial. Not affiliated with, endorsed by, or supported by Satchel.

## What you get

### To-do list

Homework appears as a native Home Assistant **to-do list**, so it shows up in
the to-do card and dashboard like any other list. Ticking an item **marks it
complete in Satchel One** - this is the one part of the integration that
writes back to the school's record. Each item carries the task type, subject,
teacher, the description and a direct link to the task.

### Calendar

The pupil's **timetable** as a calendar entity: subject, class, teacher and
room, for whatever range the calendar view asks for.

### Sensors

| Sensor | Description |
| --- | --- |
| Homework outstanding | Tasks not yet marked complete. Up to 20 listed as an attribute, each with a link. |
| Homework overdue | Outstanding tasks whose due date has passed. |
| Homework next due | Timestamp of the soonest-due task, with `days_until_due`. |
| Homework due this week | Outstanding tasks due within the next 7 days. |
| Detentions | Outstanding detentions, with the details as an attribute. |
| Behaviour points | Net total, with week/month/all-time splits **and the individual events** that made them up. |

### Binary sensors

| Binary sensor | On when |
| --- | --- |
| Overdue homework | Any outstanding task is past its due date |
| Homework due today | Any outstanding task is due today |
| Detention today | A detention is scheduled for today |

### Events

Automations can react the moment something changes, instead of polling
attributes:

| Event | Fired when | Payload |
| --- | --- | --- |
| `satchel_one_new_homework` | A task appears | `task_id`, `title`, `subject`, `teacher`, `type`, `due_on`, `url` |
| `satchel_one_homework_completed` | A task is marked complete | `task_id`, `title`, `subject` |
| `satchel_one_new_detention` | A detention appears | `detention_id`, `reason`, `date`, `location` |
| `satchel_one_behaviour_point` | Points are awarded | `points`, `severity`, `positive`, `reason`, `category`, `teacher` |

All payloads also carry `student_id` and `student_name`. `severity` is
`abs(points)`, so automations can branch on seriousness without sign maths.
Nothing is fired on the first refresh after a restart, so you are not flooded
with events for homework that already existed.

### Diagnostics

Download diagnostics from the integration page for a bug report. Credentials
are redacted and the payload deliberately contains field *names* and counts
rather than your child's homework.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/robbrad/ha-satchel-one`, category **Integration**
3. Install **Satchel One**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Satchel One**

### Manual

Copy `custom_components/satchel_one` into your Home Assistant
`config/custom_components` directory and restart.

## Configuration

Everything is set up in the UI.

Setup is three short steps:

1. **Find your school** - search Satchel's public directory by name or
   postcode. If several match, you pick from a list showing each school's town
   and postcode, so near-identical names are easy to tell apart.
2. **Sign in** with your Satchel One **parent** login.
3. **Choose a pupil**, if the account has more than one.

| Field | Notes |
| --- | --- |
| School name or postcode | Part of the name is enough |
| Email address or username | Your Satchel One **parent** login |
| Password | Stored in Home Assistant's encrypted config entry storage |
| Update interval | Minutes between polls. 15–1440, default 60. |

### More than one child

If your account has several pupils, setup asks which one this entry should
track. Add the integration again to track another — each gets its own device,
to-do list, calendar and sensors.

### Changing the poll interval

**Settings → Devices & Services → Satchel One → Configure.** Homework is set a
few times a day at most, so the hourly default is plenty — please do not poll
aggressively.

## Example automation

Nudge at teatime if anything is overdue:

```yaml
automation:
  - alias: "Homework overdue reminder"
    triggers:
      - trigger: time
        at: "17:30:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.satchel_one_alex_homework_overdue
        above: 0
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Homework overdue"
          message: >-
            {{ states('sensor.satchel_one_alex_homework_overdue') }} overdue:
            {{ state_attr('sensor.satchel_one_alex_homework_overdue', 'items')
               | map(attribute='title') | join(', ') }}
```

## How it works

Satchel One has no documented public API. This integration talks to the same
endpoints the web app does, using the OAuth2 password grant. Two quirks are
worth knowing if you ever debug it:

- `school_id` is **mandatory** in the password grant. Without it the server
  answers `invalid_credentials` even for a correct password — which is why
  setup starts by resolving your school to its numeric id, via Satchel's
  public `school_search` endpoint.
- The token endpoint lives at the **domain root**. `/api/oauth/token` is
  CDN-fronted and never authenticates.
- Data requests authenticate with the `smhw_token` field from the grant, **not**
  `access_token`, and the API version travels as a vendor media type
  (`Accept: application/smhw.v2021.5+json`).
- The CDN in front of the API caches failed responses, so every request carries
  a cache-busting parameter.
- This integration has **no Python dependencies** — everything is JSON over the
  `aiohttp` session Home Assistant already provides.

The client refreshes with the refresh token rather than re-sending your
password on every poll.

### About the client credentials

`const.py` contains a `CLIENT_ID` and `CLIENT_SECRET`. These are **not yours** —
they are the public single-page-app credentials that Satchel ships in its own
JavaScript bundle, readable by anyone who opens the site. The password grant
will not work without them and there is no other client to use. No personal
secret is committed to this repository.

Because these endpoints are undocumented, **Satchel can change them without
notice** and break this integration.

## Writing back to Satchel

Ticking a homework item in Home Assistant marks it complete **in Satchel One**,
under your child's record. Everything else this integration does is read-only.
If you would rather it never wrote anything, hide or disable the to-do entity.

## Privacy

Your credentials go to `satchelone.com` and nowhere else. There is no
telemetry, and no third-party service is involved. Credentials live in Home
Assistant's config entry storage; the integration prompts you to re-enter your
password if Satchel ever rejects it.

**When reporting a bug, redact your email, password, tokens and your child's
name from any logs you attach.**

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
pytest
ruff check . && ruff format --check .
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org) —
the release version is derived from them by Commitizen, so `feat:` and `fix:`
prefixes matter. `pre-commit install` sets up the same checks CI runs.

## Contributing

Issues and PRs welcome. Please never paste real credentials, tokens or a
child's personal data into an issue, a test fixture or a log.

## Licence

[MIT](LICENSE)
