"""Platforms: HOW a selection is packaged for the experts who check it. One module per platform:

  audio-clips   short WAV clips plus a spreadsheet for the verdicts (birds, bats)
  mothbot       packages for the Mothbot labelling site: crops, records, clusters (images)

A new platform needs only a module with GROUPS (the groups it takes) and prepare(selection, out,
settings=..., blind=..., bucket=..., source_root=..., **options) -> summary dict, and a line below.
The sampling (sampling.py) stays the same whichever platform is used.
"""
PLATFORMS = {
    "audio-clips": "ceh_biomonitoring.validation.platforms.audio_clips",
    "mothbot": "ceh_biomonitoring.validation.platforms.mothbot",
}
DEFAULT_FOR = {"birds": "audio-clips", "bats": "audio-clips", "images": "mothbot"}
