# Two-person Google Meet

Use a Chrome profile already signed in to two Google accounts (`authuser=0`
hosts; `authuser=1` joins).

Generate:

```bash
netgent -g api_keys.json '{}' \
  examples/video_conference/google-meet-two-person/prompts/google-meet-two-person_prompts.json \
  --user-data-dir examples/user_data \
  -o examples/video_conference/google-meet-two-person/results/google-meet-two-person_result.json
```

Replay:

```bash
netgent -e \
  examples/video_conference/google-meet-two-person/results/google-meet-two-person_result.json \
  --user-data-dir examples/user_data
```

Success requires the waiting-room text to disappear and the joiner-side
`Meeting details` button to appear. Metrics are written to
`/out/google_meet_two_person_metrics.json`.
