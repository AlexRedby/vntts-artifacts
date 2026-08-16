# TODO

Keep this file limited to actionable unfinished contract work. Remove completed
items and empty sections after verification; keep stable contract behavior and
migration guidance in the README or dedicated documentation.

## Stabilize the authoring exchange

- [ ] Add synthetic compatibility fixtures covering extractor source output,
      a generation queue, generated-audio publication, final game-pack assembly,
      checksum failure, and VNTTS consumption.

## Release and adoption

- [ ] Publish one immutable `vntts-artifacts` release containing the completed
      contracts, then pin both VNTTS and `reverse1999-extractor` to that same
      release.
- [ ] Add a compatibility matrix documenting which producer and consumer
      versions support each story-index, voice-manifest, generated-audio,
      generation-queue, and game-pack schema version.
