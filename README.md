# Satchel One for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate HACS](https://github.com/robbrad/ha-satchel-one/actions/workflows/hacs_validation.yml/badge.svg)](https://github.com/robbrad/ha-satchel-one/actions/workflows/hacs_validation.yml)
[![Tests](https://github.com/robbrad/ha-satchel-one/actions/workflows/tests.yml/badge.svg)](https://github.com/robbrad/ha-satchel-one/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Bring your child's **Satchel One** (formerly Show My Homework) account into
Home Assistant: outstanding homework, what is overdue, what is due next,
detentions and behaviour points.

> Unofficial. Not affiliated with, endorsed by, or supported by Satchel.

## Sensors

| Sensor | Description |
| --- | --- |
| Homework outstanding | Tasks not yet marked complete. Up to 20 listed as an attribute. |
| Homework overdue | Outstanding tasks whose due date has passed. |
| Homework next due | Timestamp of the soonest-due task, with `days_until_due` and the task details. |
| Homework due this week | Outstanding tasks due within the next 7 days. |
| Detentions | Outstanding detentions, with the details as an attribute. |
| Behaviour points | Net total, with positive/negative splits for the week, month and all time. |

Each task attribute carries the title, subject, teacher, due date, type and
submission status — enough to build a dashboard card without extra templates.

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

| Field | Notes |
| --- | --- |
| School name | Looked up against Satchel's public school directory. Try the full name or your postcode. |
| Email address or username | Your Satchel One **parent** login |
| Password | Stored in Home Assistant's encrypted config entry storage |
| Update interval | Minutes between polls. 15–1440, default 60. |

### More than one child

If your account has several pupils, setup asks which one this entry should
track. Add the integration again to track another — each gets its own device
and sensors.

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
  setup starts by resolving your school's name to its numeric id.
- Data requests authenticate with the `smhw_token` field from the grant, **not**
  `access_token`, and the API version travels as a vendor media type
  (`Accept: application/smhw.v2021.5+json`).

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
