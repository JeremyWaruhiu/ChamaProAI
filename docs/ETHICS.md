# Ethics and data protection

## Kikuyu interview audio

The Kikuyu audio used in this project was collected with written informed
consent from the participant, in accordance with the Kenya Data Protection
Act, 2019.

The recordings are personal data: they capture the voice of an identifiable
person. For that reason:

- **The recordings are held offline** and are deliberately excluded from this
  repository, which is public. `.gitignore` blocks `*.wav`, `*.m4a`, `*.mp3`,
  `*.flac` and `*.ogg` anywhere in the tree, and everything under `data/`
  other than the files listed in it.
- **The signed consent form is held offline** and is likewise excluded.
  `docs/consent/` is gitignored as an additional safeguard.
- **Only a text index of the audio set**, `data/manifest.csv`, is versioned
  here, so the experiments can refer to recordings without containing them.

The consent form is reproduced in the appendix of the project report.

## FinAccess Household Survey

The FinAccess 2024 microdata is licensed for research use and is not
redistributed here. Files derived from it at row level (the modelling frames
and explorer outputs) are also excluded; only aggregate profiles and model
results are committed. See [data/README.md](../data/README.md).
