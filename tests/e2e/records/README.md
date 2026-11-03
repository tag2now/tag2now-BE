# Match-records replay

Runs the real `be` and `save-admin` images together and reproduces RPCN's saves,
then checks that `match_results` says who played whom. Spec: `docs/spec/11-records.md`.

A game save is two steps on the RPCN host --- a new `.tdt` under a new `data_id`,
then the `tus_data` row pointing at it --- so the replay does exactly those and
needs no game. Rooms are written the way the collector writes them.

```bash
SAVE_ADMIN_DIR=../tag2now-save-admin tests/e2e/records/run.sh
```

`SAVE_ADMIN_DIR` defaults to the sibling checkout. Logs go to
`test-results/e2e-records/`; the stack and its volumes are removed afterwards.

**Not part of the pre-commit suite.** It builds a second repository, so its
result depends on that checkout. Run it when match records, the save-admin
answer it reads, or the deploy order between them changes.

It cannot tell whether the save offsets are right, since the saves are written
with the same constants they are read with, nor how real rooms and saves line
up in time. Those are checked against production.

| Phase | Scenarios |
|-------|-----------|
| `seed` | 470 saves already there, before be starts |
| `scenarios` | 1 baseline, 2 tag match, 3 solo, 4 a reused room, 5 a result on the rematch's start save, 6 a re-upload, 7 an opponent who quit, 8 no room, 9 two wins in one save, 10 an unreadable save, 11 a lower `data_id` committed later |
| `during-outage`, `after-outage` | 12 a match played while save-admin is down |
| `before-restart`, `after-restart` | 13 a be restart, and no event left dead |
