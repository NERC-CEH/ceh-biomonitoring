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

Five consecutive photos from an automated moth trap (28 July 2022), for detection, classification and tracking. Downloaded from the AMI Data Companion's test images when first used; not copied into this repository.

| File | Species | Recorded by | Licence | Source |
|---|---|---|---|---|
| `20220728232239-00-69.jpg` |  | Rolnick Lab, Mila: AMI Data Companion test images | AGPL-3.0 (the AMI Data Companion repository) | [source](https://github.com/RolnickLab/ami-data-companion/tree/main/trapdata/tests/images/sequential) |
| `20220728232322-00-70.jpg` |  | Rolnick Lab, Mila: AMI Data Companion test images | AGPL-3.0 (the AMI Data Companion repository) | [source](https://github.com/RolnickLab/ami-data-companion/tree/main/trapdata/tests/images/sequential) |
| `20220728232445-00-71.jpg` |  | Rolnick Lab, Mila: AMI Data Companion test images | AGPL-3.0 (the AMI Data Companion repository) | [source](https://github.com/RolnickLab/ami-data-companion/tree/main/trapdata/tests/images/sequential) |
| `20220728232552-00-72.jpg` |  | Rolnick Lab, Mila: AMI Data Companion test images | AGPL-3.0 (the AMI Data Companion repository) | [source](https://github.com/RolnickLab/ami-data-companion/tree/main/trapdata/tests/images/sequential) |
| `20220728232652-00-74.jpg` |  | Rolnick Lab, Mila: AMI Data Companion test images | AGPL-3.0 (the AMI Data Companion repository) | [source](https://github.com/RolnickLab/ami-data-companion/tree/main/trapdata/tests/images/sequential) |

## Licences and changes

- **Birds and bats** are open recordings shared on iNaturalist and published through GBIF, under **CC0** (no conditions) or **CC BY 4.0** (credit the recordist: Andrew Skotnicki for the Wren). Thank you to everyone listed above. The bird recordings are the **first 30 seconds** of the originals; the bat recordings are unchanged. The file names give the recording date (time of day isn't known, so it's set to midday for birds and 22:00 for bats) and the GBIF record number.
- **Images** belong to the [AMI Data Companion](https://github.com/RolnickLab/ami-data-companion) (Rolnick Lab, Mila), whose repository is licensed AGPL-3.0. They're **not copied into this repository**: `cehbio examples` downloads them from there, at a fixed version, when first used.

Better UK examples (for instance UKCEH's own trap photos, released under an open licence) can replace these: add the files and their entries to `examples.yml`, and `pytest` checks they match.
