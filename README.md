# anonymize_data

Utilities and pipelines for anonymizing medical video and DICOM data.

## Before Running

Before using DVC-managed files, update them to match the latest table version from `HUTOM_DB_SERVER`.

Set the DVC remote first if your environment uses the SSH storage.

Current example:

```ini
[core]
    remote = nas6_datateam
['remote "nas6_datateam"']
    url = ssh://da_cyh_0@192.168.16.60/nas/nas6/DataTeam/METADB
```

If your SSH user is different, change `da_cyh_0` to your account and then download the dataset.

```bash
cd h_anonypy/
dvc pull
```

If you are using a fresh environment, install the package in editable mode.

```bash
pip install -e .
```

If your environment is offline or build isolation causes installation issues, try:

```bash
pip install -e . --no-build-isolation
```

## Config

`main.py` reads a JSON or YAML config file.

Example config: [config.example.json](/disk1/users/da_cyh_0/PROJECT/DATA/anony/config.example.json)

Key fields:

- `video_meta_fname`: path to the video metadata Excel file
- `id_fname`: path to the HUTOM ID Excel file
- `n_digits`: zero-padding width for generated IDs
- `recodec`: if `true`, run `ffmpeg`; if `false`, copy files instead
- `verbose`: print pipeline progress when `true`
- `datasets`: list of dataset jobs to process

## Run

Run the video pipeline with a config file:

```bash
python main.py config.example.json
```

You can also use YAML:

```bash
python main.py config.yaml
```

## Pipeline Flow

The current video pipeline runs in this order:

1. Load shared metadata files
2. Extract base information from raw video files
3. Extract video metadata and capture frames
4. Prepare anonymization outputs and save preview metadata
5. Run anonymization
