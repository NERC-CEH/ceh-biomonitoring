# Recorders and file names

Most recorders and traps put the date and time in each file's name. Tell `cehbio` which one you used and every result gets a `file_datetime` column, plus `device_serial` where the name includes the unit's ID.

```bash
cehbio run bats --folder E:/rec --deployment wood-1 --device audiomoth
cehbio devices                                   # the recorders it knows
```

## Recorders it knows

| `--device` | Recorder | File names look like |
|---|---|---|
| `audiomoth` | AudioMoth | `20240705_043000.WAV` |
| `song-meter` | Wildlife Acoustics Song Meter (Mini, Micro, SM4) | `SMA01234_20240705_043000.wav` |
| `ami-trap` | AMI light trap | `20240725204340-snapshot.jpg` |
| `lepisense` | LepiSense / AMI-mini | `123456789012345-20260806T025318.jpg`, `ami-mini-20250428T210338.jpg` |

The device also stops mistakes: e.g. a light trap can't be used with the bats pipeline.

## Other file names

Describe them in plain language with `--timestamp-pattern`:

```bash
--timestamp-pattern "SERIAL_YYYYMMDD_hhmmss"     # e.g. SMA01234_20240705_043000.wav
--timestamp-pattern "site*_YYYY-MM-DD_hh-mm-ss"  # e.g. site3_2024-07-05_04-30-00.wav
```

| Write | Means |
|---|---|
| `YYYY` | year |
| `MM` | month (**capital** M) |
| `DD` | day |
| `hh` | hour (24-hour) |
| `mm` | minutes (**small** m) |
| `ss` | seconds |
| `SERIAL` | the recorder's ID |
| `*` | anything |

Anything else, such as `_`, `-` or `T`, must match exactly.

## Time zones

The time in a file name is whatever the recorder's clock said. Some recorders are set to local time, some to UTC (AudioMoth uses UTC unless set otherwise), and some to the time zone of wherever they were set up. This belongs to each **deployment**, not to the type of recorder, so note it down when you deploy. `cehbio` reports times exactly as they are in the file names and does not convert them.

**A quick check:** light traps usually start around dusk. If a trap's first image each night is hours away from local dusk, its clock is probably on UTC or another time zone.

## Your own recorder

If you use a recorder often, save it as a device so you don't have to type the pattern each time. Create `~/.config/ceh-biomonitoring/devices/my-recorder.yml`:

```yaml
name: my-recorder
title: My recorder
media: audio                      # audio or images
extensions: [.wav]
timestamp:
  patterns:
    - "site*_YYYY-MM-DD_hh-mm-ss"
params:                           # optional: settings for particular pipelines
  bats:
    detection_threshold: 0.4
```

Then use `--device my-recorder`. Settings from a device are used unless you give others with `--config` or `--set`.
