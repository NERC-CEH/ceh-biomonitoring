# Example data

Small sets of real data for trying each pipeline, so anyone can check their installation works:

```bash
cehbio examples                 # what there is
cehbio examples run birds       # run one pipeline on its examples and check the result
cehbio examples run all         # every pipeline you have installed
```

Each run says **PASS** (with what it found) or **PROBLEM**. The results go in your outputs folder under `example-<pipeline>`. The examples check that the pipeline runs; they're far too small to judge how accurate it is.

Every file is checked against its fingerprint (sha256) before use. The list, with sources, is in [`src/ceh_biomonitoring/examples.yml`](../src/ceh_biomonitoring/examples.yml).

## Birds

Three 30 s recordings of common UK birds (Robin, Blackbird, Wren), cut from open recordings on GBIF / iNaturalist.

| File | Species | Recorded by | Licence | Source |
|---|---|---|---|---|
| `20260124_120000_erithacus-rubecula_gbif6130110847.wav` | *Erithacus rubecula* | Richard M | CC0 1.0 | [GBIF record](https://www.gbif.org/occurrence/6130110847) |
| `20260316_120000_turdus-merula_gbif6178462112.wav` | *Turdus merula* | Richard M | CC0 1.0 | [GBIF record](https://www.gbif.org/occurrence/6178462112) |
| `20260123_120000_troglodytes-troglodytes_gbif6130414475.wav` | *Troglodytes troglodytes* | Andrew Skotnicki | CC BY 4.0 | [GBIF record](https://www.gbif.org/occurrence/6130414475) |

## Bats

Three short full-spectrum (256 kHz) recordings of UK bats: Common Pipistrelle, Daubenton's bat and Noctule.

| File | Species | Recorded by | Licence | Source |
|---|---|---|---|---|
| `20260825_220000_pipistrellus-pipistrellus_gbif6519421762.wav` | *Pipistrellus pipistrellus* | Kian Hayles-Cotton | CC0 1.0 | [GBIF record](https://www.gbif.org/occurrence/6519421762) |
| `20220713_220000_myotis-daubentonii_gbif3874157579.wav` | *Myotis daubentonii* | Tom August | CC0 1.0 | [GBIF record](https://www.gbif.org/occurrence/3874157579) |
| `20260427_220000_nyctalus-noctula_gbif6441300599.wav` | *Nyctalus noctula* | Desmond Ney | CC0 1.0 | [GBIF record](https://www.gbif.org/occurrence/6441300599) |

## Images

Five consecutive photos, 10 seconds apart, from a UKCEH automated moth trap at "Prickly pear" on **Anguilla** (AMBER project), 4 January 2025 from 03:12 local time. Each has about 25 moths, many of them seen in all five, so the run shows detection, identification with the **Anguilla species model** (`region=anguilla`) and tracking.

| File | Time (local) |
|---|---|
| `20250104031250-snapshot.jpg` | 03:12:50 |
| `20250104031259-snapshot.jpg` | 03:12:59 |
| `20250104031310-snapshot.jpg` | 03:13:10 |
| `20250104031319-snapshot.jpg` | 03:13:19 |
| `20250104031330-snapshot.jpg` | 03:13:30 |

Recorded by UKCEH for the AMBER project. **CC BY 4.0**: credit UKCEH. Full size (4096 × 2160) and unchanged; their EXIF data holds only the date, time and time-zone offset.

The detector is slow without a GPU: on one CPU core the five photos take about 20 minutes, and a laptop with several cores is quicker. The run prints a line per photo so you can see it working.

## Licences and changes

- **Birds and bats** are open recordings shared on iNaturalist and published through GBIF, under **CC0** (no conditions) or **CC BY 4.0** (credit the recordist: Andrew Skotnicki for the Wren). Thank you to everyone listed above. The bird recordings are the **first 30 seconds** of the originals; the bat recordings are unchanged. The file names give the recording date (time of day isn't known, so it's set to midday for birds and 22:00 for bats) and the GBIF record number.
- **Images** are UKCEH's own (AMBER project), released under **CC BY 4.0**: credit UKCEH.

To change an example, add the files and their entries to `examples.yml`; `pytest` checks they match.
