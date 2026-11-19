# anonymize_data

Utilities and pipelines for anonymizing medical video and DICOM data.

[한국어 README](README_KOR.md)

## Setup

Metadata tables are loaded directly from the DB. No local metadata files are required.
When running from this repository, editable installation is not required just to use
`main.py`.

This repository is managed with [Pixi](https://pixi.prefix.dev/). Python 3.11,
runtime dependencies, and FFmpeg are defined in `pixi.toml`; exact package
versions are recorded in `pixi.lock`. From this directory, install the runtime
environment with:

```bash
pixi install --locked
```

For development, install the `dev` environment and run its checks:

```bash
pixi install -e dev --locked
pixi run -e dev test
pixi run -e dev check
```

Run commands inside the runtime environment with `pixi run`, or enter its shell:

```bash
pixi run python --version
pixi shell
```

DB credentials and table names can be left as `null` in the config. The CLI will
ask for them at runtime; passwords are entered with hidden input.

> **Important:** Before using these variables, you must ask the administrator for
> the correct DB connection settings and table names.

## Config

`main.py` reads a JSON config file.

Example configs:

- Video JSON: [video.example.json](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/video.example.json)
- DICOM JSON: [dicom.example.json](/disk1/users/da_cyh_0/PROJECT/DATA/anony/configs/dicom.example.json)

The following tables describe the supported config options. Defaults apply when
an option is omitted; the example configs explicitly enable some optional work.

### Pipeline options

| Option | Applies to | Default | Behavior |
| --- | --- | --- | --- |
| `pipeline` | Both | Inferred from table keys | `video` or `dicom`. If omitted, `video_meta`/`VIDEO_META` selects video; otherwise `image_meta`/`IMAGE_META` selects DICOM. Set explicitly when both tables are present. |
| `metadata_source` | Both | Required, or top-level DB settings | DB connection and source tables; see below. |
| `n_digits` | Both | `4` | Minimum zero-padding width for newly assigned IDs, e.g. `URO0001`. |
| `run_anonymization` | Both | Video: `false`; DICOM: `true` | `true` writes anonymized outputs. `false` still reads metadata, assigns IDs, builds jobs, and writes metadata exports. Video captures can still be generated when `capture: true`. |
| `verbose` | Both | `true` | Print pipeline progress. |
| `datasets` | Both | Required | Non-empty list of dataset jobs. Jobs run in list order. |
| `recodec` | Video | `true` | When `run_anonymization: true`, `true` transcodes with FFmpeg; `false` copies the original file. Existing output files are overwritten in both modes. |
| `preserve_aspect_ratio` | Video | `true` | With `recodec: true`, `true` fits the video inside 1280×1024, preserves its ratio, and adds centered black padding. `false` stretches it to 1280×1024 without padding, with square pixels. Must be a boolean. Ignored when `recodec: false`; a custom `ffmpeg_cmd` takes precedence. |
| `capture` | Video | `false` | Generate a JPG capture image during metadata extraction. Independent of `run_anonymization`. |
| `capture_deinterlace` | Video | `false` | When `capture: true`, use FFmpeg `yadif` for frame capture if `true`; otherwise use OpenCV. |
| `ffmpeg_cmd` | Video | Built-in command | Optional FFmpeg argument list. The third element (index `2`) is replaced with the input path and the last element with the output path; use `null` placeholders there. The custom list replaces the built-in command, including resize settings. Overwrite mode (`-y`) is enforced. |
| `video_meta_columns` | Video | `null` | Ordered column-name list for `DB_FORMAT_<organ>_<importdate>.xlsx`. Omit or use an empty list to skip this extra export. Known DB column labels are mapped to internal metadata columns; unavailable values are blank. The regular metadata export is still written. |
| `ct_meta_format` | DICOM | Repository `configs/CT_META_FORMAT.xlsx` | Excel template for `DB_FORMAT_<organ>_<importdate>.xlsx`, written alongside `DICOM_META` even when `run_anonymization: false`. Maps `hutom id` from `hutom_id` and `patient id` from `PatientID`, keeping the first row per assigned `hutom_id` and omitting unassigned IDs. Preserves template column order, sheet name, and header formatting; the source template is unchanged. Custom relative paths resolve from the current working directory. |

The built-in video command produces H.264 (`libx264`, High profile, level 4.0),
`yuv420p`, 1280×1024, 30 fps, and a target video bitrate of `6962k`. Audio uses
AAC-LC, 48 kHz, stereo, and `128k`. MP4 output uses `+faststart`.

For example, a 1920×1080 video becomes 1280×720 with 152 pixels of black padding
above and below when `preserve_aspect_ratio: true`. With `false`, it fills the
1280×1024 frame by stretching. In JSON, use lowercase `true`/`false`, without quotes.

### Dataset options

| Option | Applies to | Default | Behavior |
| --- | --- | --- | --- |
| `datasets[].video_dir` | Video | Required | Input dataset root, as a path string or non-empty list of paths. Multiple roots share ID assignment within the job. |
| `datasets[].dicom_dir` | DICOM | Required | Input dataset root, as a path string or non-empty list of paths. Multiple roots share ID assignment within the job. |
| `datasets[].output_dir` | Both | Required | Output root. Anonymized files are saved under `ANONYMOUS/`; metadata exports and video captures also use this root. |
| `datasets[].center` | Both | Required | Source institution/center label written to metadata as `Center`. |
| `datasets[].importdate` | Both | Required | Import date written as `ImportDate` and used in export filenames. Use a string such as `"20261116"`. |
| `datasets[].organ` | Both | Required | Metadata `data_type` and prefix for new `hutom_id` values, e.g. `URO0001`. DICOM also uses the matching path component as its relative-path root. For `organ: URO`, either a `URO` folder or a `RUS_Kidney` folder is accepted; an exact `URO` match takes priority. |
| `datasets[].start_id` | Both | `null` | Optional positive integer for the first new ID, overriding the DB-derived next number. Existing matched IDs are still reused. |

### DB metadata options

Only DB metadata loading is supported. These tables are read by the pipeline;
metadata results are exported to Excel rather than inserted into the DB.

| Option | Default | Behavior |
| --- | --- | --- |
| `metadata_source.type` | `db` when DB/table settings are present | Must be `db`. |
| `metadata_source.db` | Required | Connection object. `metadata_source.database` is an alias. Top-level `db`/`database` and `tables` can also be used when `metadata_source` is omitted. |
| `metadata_source.db.url` | Unset | Complete SQLAlchemy connection URL. If set, takes precedence over the individual connection fields below. |
| `metadata_source.db.driver` | `postgresql+psycopg2` | SQLAlchemy dialect and driver. |
| `metadata_source.db.user` | Prompted if missing or `null` | DB username; `username` is an alias. |
| `metadata_source.db.password` | Prompted if missing or `null` | DB password; `pwd` is an alias. Input is hidden when prompted. |
| `metadata_source.db.password_env` | Unset | Environment variable containing the password, used when `password` is `null` or absent. `pwd_env` is an alias. If no usable password is found, prompt for it. |
| `metadata_source.db.host` | Prompted if missing or `null` | DB hostname or address. |
| `metadata_source.db.port` | Prompted if missing or `null` | DB port, converted to an integer. |
| `metadata_source.db.database` | Prompted if missing or `null` | DB name; `db` and `name` are aliases inside the connection object. |
| `metadata_source.tables` | Required | Mapping of logical table names to DB table names. Use `schema.table`; an unqualified name uses schema `public`. Include required keys even if their values are `null`; `null` values are prompted at runtime. |
| `metadata_source.tables.video_meta` | Required for video | Existing video metadata table. `VIDEO_META` is an alias. |
| `metadata_source.tables.image_meta` | Required for DICOM | Existing image metadata table. `IMAGE_META` is an alias. |
| `metadata_source.tables.hids_all` | Required for both | Existing ID linkage table used to determine the next ID. `hutom_id` and `HUTOM_ID` are aliases. |

DB metadata config example:

```json
{
  "metadata_source": {
    "type": "db",
    "db": {
      "driver": "postgresql+psycopg2",
      "user": null,
      "password": null,
      "host": null,
      "port": null,
      "database": null
    },
    "tables": {
      "video_meta": null,
      "image_meta": null,
      "hids_all": null
    }
  }
}
```

Missing connection values require interactive input. Video needs `video_meta`
and `hids_all`; DICOM needs `image_meta` and `hids_all`.

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
pixi run python main.py configs/video.example.json
```

Run the DICOM pipeline with a config file:

```bash
pixi run python main.py configs/dicom.example.json
```

## Pipeline Flow

Video pipeline:

1. Load shared metadata tables from the DB
2. Extract base information from raw video files and assign `hutom_id` values after checking for duplicates
3. Extract video metadata and capture frames
4. Prepare anonymization outputs and save preview metadata
5. Run anonymization

DICOM pipeline:

1. Load shared metadata tables from the DB
2. List sample folders in the input directory
3. Extract representative DICOM metadata for each sample
4. Check duplicates and assign `hutom_id`
5. Run anonymization and save preview metadata

For DICOM, the metadata-saving stage produces both the series-level
`DICOM_META_<organ>_<importdate>.xlsx` and the ID-level
`DB_FORMAT_<organ>_<importdate>.xlsx`. Multiple series with the same `hutom_id`
produce one row in the CT template export; the full preview retains all rows.
