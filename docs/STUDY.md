# Study & coach — the way of study

The witness app shows the way of study by reading the core's doors (`nh_org/study.py`). It keeps no
learner state of its own.

## Read / compose (done)

| call | core door | what it is |
|---|---|---|
| `study.teachings()` | `GET /teachings` | the Words in Red, by group (Sermon, Discourses, I AM, Parables) |
| `study.decks()` | `GET /decks` | the library decks |
| `study.coach_overview(subj)` | `GET /coach/overview` | a subject's tracks and units |
| `study.coach_next(subj)` | `GET /coach/next` | the shepherd's one next unit |
| `study.playbook()` | `GET /playbook` | the playbook entries |

## Writes — a seam, not performed here

Recording mastery (`/coach/mastery`), creating or exporting/importing a study (`/study`,
`/study/export`, `/study/import`), saving a trajectory (`POST /trajectory`) and submitting a playbook
entry (`/playbook/submit`) are the learner's own acts, kept as their record. The app composes them
only as the learner's authorized request; those doors stay out of `core_client.CORE_DOORS`
(`tests/test_study.py` pins that).
