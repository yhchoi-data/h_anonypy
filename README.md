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

For development tools such as `pytest`, `pre-commit`, `ruff`, and `black`, install the
`dev` extra:

```bash
pip install -e ".[dev]"
```

If your environment is offline or build isolation causes installation issues, try:

```bash
pip install -e . --no-build-isolation
```

## Config

`main.py` reads a JSON or YAML config file.

Example configs:

- Video JSON: [video.example.json](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/video.example.json)
- Video YAML: [video.example.yaml](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/video.example.yaml)
- DICOM JSON: [dicom.example.json](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/dicom.example.json)
- DICOM YAML: [dicom.example.yaml](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/dicom.example.yaml)

Key fields:

- `pipeline`: `video` or `dicom`
- `video_meta_fname`: path to the video metadata Excel file
- `image_meta_fname`: path to the DICOM metadata Excel file
- `id_fname`: path to the HUTOM ID Excel file
- `n_digits`: zero-padding width for generated IDs
- `run_anonymization`: if `true`, run anonymization; if `false`, only build metadata and jobs
- `recodec`: video only. If `run_anonymization` is `true`, run `ffmpeg` when `true`, or copy files when `false`
- `verbose`: print pipeline progress when `true`
- `datasets`: list of dataset jobs to process

## Input Layout

Both pipelines assume the input directory follows this structure:

```text
data_dir/
  sample_folder/
    data/  # video files or DICOM folders/files
```

In other words:

- `data_dir`: the dataset root passed as `video_dir` or `dicom_dir`
- `sample_folder`: one case or patient folder under the dataset root
- `data`: the actual video files or DICOM data stored under each sample folder

This layout should be preserved for the pipeline to discover samples correctly.

Example video layout:

```text
video_dir/
  patient_001/
    clip_01.mp4
    clip_02.mp4
  patient_002/
    exam_video.mov
```

Example DICOM layout:

```text
dicom_dir/
  patient_001/
    DATA/
      20250725/
        092454/
          7866398/
            EX1/
              SE1/
                IMG0001
                IMG0002
  patient_002/
    DATA/
      ...
```

## Run

Run the video pipeline with a config file:

```bash
python main.py configs/video.example.json
```

Run the DICOM pipeline with a config file:

```bash
python main.py configs/dicom.example.json
```

You can also use YAML:

```bash
python main.py configs/video.example.yaml
python main.py configs/dicom.example.yaml
```

## Pipeline Flow

Video pipeline:

1. Load shared metadata files
2. Extract base information from raw video files and assign `hutom_id` values after checking for duplicates
3. Extract video metadata and capture frames
4. Prepare anonymization outputs and save preview metadata
5. Run anonymization

DICOM pipeline:

1. Load shared metadata files
2. List sample folders in the input directory
3. Extract representative DICOM metadata for each sample
4. Check duplicates and assign `hutom_id`
5. Run anonymization and save preview metadata
