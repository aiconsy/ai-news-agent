# Changelog

## 1.2.0

- Headlines are remembered only after a briefing is saved. A failed model call no longer drops those stories.
- Speech keeps the space after initials (`U.S. officials`). Broad words such as `default` are no longer treated as crises.
- RSS decks that are already long enough are not fetched again. Tracking parameters no longer split one story into two.
- Feed redirects onto private or metadata hosts are refused, and feeds over 2 MB are skipped.
- The feed list ships inside the package. `FEEDS_PATH` or an existing `config/feeds.json` overrides it.
- Unused `pydub` and `piper-tts` installs were removed. Piper remains an optional external binary.

## 1.1.0

- Ranking uses word boundaries, and only a capped set of ambiguous headlines reaches a model.
- Synthesis receives short leads for new high-value stories, under a character budget.
- Seen headlines refresh their timestamp, so the dedup window actually slides.

## 1.0.0

- First public release of the hourly RSS briefing pipeline.
