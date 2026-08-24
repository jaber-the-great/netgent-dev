# Set-of-Marks geometry check

`evals/som_check.py`, headless Chromium. For each drawn mark, elementFromPoint at the box center (in the element's own frame, composed-tree/shadow aware): `hit` = lands on the element; `covered` = a larger element sits on top (modal/backdrop/fixed header) and the mark is drawn hollow — the correct outcome; `miss` = a geometry error. `identity %` = (hit + covered) / marks. Annotated PNGs in `evals/results/som/`.

| site | viewport | listed | in view | marks | identity % | hit | covered | miss | label overlaps | unmarked in view | render ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| youtube | 1280x800 | 12 | 12 | 12 | 100.0 | 12 | 0 | 0 | 0 | 0 | 51.0 |
| twitch | 1280x800 | 60 | 45 | 45 | 97.8 | 41 | 3 | 1 | 0 | 0 | 53.3 |
| reddit | 1280x800 | 60 | 52 | 52 | 98.1 | 46 | 5 | 1 | 0 | 0 | 41.5 |
| forms | 1280x800 | 60 | 27 | 27 | 100.0 | 26 | 1 | 0 | 0 | 0 | 22.6 |
| challenge | 1280x800 | 41 | 14 | 14 | 92.9 | 13 | 0 | 1 | 0 | 0 | 24.9 |
| fixed+modal | 1280x800 | 7 | 6 | 6 | 100.0 | 2 | 4 | 0 | 0 | 0 | 47.8 |
| rtl | 1280x800 | 4 | 4 | 4 | 100.0 | 4 | 0 | 0 | 0 | 0 | 12.0 |
| canvas | 1280x800 | 2 | 2 | 2 | 100.0 | 2 | 0 | 0 | 0 | 0 | 15.9 |
| forms-mobile | 390x844 | 60 | 13 | 13 | 92.3 | 12 | 0 | 1 | 0 | 0 | 8.8 |
