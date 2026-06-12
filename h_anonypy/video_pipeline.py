import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePath

import numpy as np
import pandas as pd

from .modules_video import (
    assign_stereo_ch_names,
    capture_key_frames_by_video,
    check_patient_ids,
    check_split_screen,
    get_video_infomation,
    get_video_metadata_ffprobe,
    get_video_metadata_opencv,
    infer_capture_mode,
)
from .metadata_source import load_shared_metadata, normalize_metadata_source

DEFAULT_FFMPEG_CMD = [
    "ffmpeg",
    "-i",
    None,
    "-c:v",
    "libx264",
    "-profile:v",
    "high",
    "-level",
    "4.0",
    "-pix_fmt",
    "yuv420p",
    "-s",
    "1280x1024",
    "-r",
    "30",
    "-b:v",
    "6962k",
    "-c:a",
    "aac",
    "-profile:a",
    "aac_low",
    "-ar",
    "48000",
    "-ac",
    "2",
    "-b:a",
    "128k",
    "-movflags",
    "+faststart",
    None,
]


def load_config(config_path):
    config_path = Path(config_path)
    suffix = config_path.suffix.lower()

    with config_path.open("r", encoding="utf-8") as file:
        if suffix == ".json":
            return json.load(file)
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError(
                    "YAML config requires PyYAML. Install `pyyaml` or use JSON."
                ) from exc
            return yaml.safe_load(file)

    raise ValueError(f"Unsupported config format: {config_path}")


def normalize_config(config):
    datasets = config.get("datasets")
    if not datasets:
        raise ValueError("Config must include a non-empty 'datasets' list.")

    return {
        "metadata_source": normalize_metadata_source(config),
        "n_digits": config.get("n_digits", 4),
        "run_anonymization": config.get("run_anonymization", False),
        "recodec": config.get("recodec", True),
        "verbose": config.get("verbose", True),
        "capture": config.get("capture", False),
        "capture_deinterlace": config.get("capture_deinterlace", False),
        "ffmpeg_cmd": config.get("ffmpeg_cmd", DEFAULT_FFMPEG_CMD.copy()),
        "video_meta_columns": config.get("video_meta_columns"),
        "datasets": datasets,
    }


def log(message, verbose):
    if verbose:
        print(message)


def get_hash_column(video_meta):
    for col in ["Hash", "hash"]:
        if col in video_meta.columns:
            return col
    raise KeyError("VIDEO_META must include either 'Hash' or 'hash' column.")


def get_next_hutom_id(hids_all, organ, n_digits):
    hids = hids_all[hids_all["hutom_id"].astype(str).str.contains(organ, na=False)]
    hids = hids[~hids["hutom_id"].astype(str).str.contains("FDA", na=False)]
    hids = hids.sort_values("hutom_id")
    existing_ids = hids["hutom_id"].tolist()
    nums = [int(m.group(1)) for s in existing_ids if (m := re.search(r"(\d+)$", s))]
    if not nums:
        return 1
    return np.sort(nums)[-1] + 1


def resolve_start_id(dataset_config, db_next_id):
    start_id = dataset_config.get("start_id")
    if start_id is None:
        return db_next_id

    try:
        start_id = int(start_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("dataset start_id must be a positive integer.") from exc

    if start_id < 1:
        raise ValueError("dataset start_id must be a positive integer.")
    return start_id


def build_rawdata_path(filepath):
    path = PurePath(filepath)
    directory = PurePath(*path.parts[:-1])
    path_str = str(directory)
    return path_str.replace("/nas/nas6/DataTeam", "/Volume/RawData", 1)


DB_FORMAT_COLUMN_MAP = {
    "hutom id": "hutom_id",
    "patient id": "patient_id",
    "rawdata_filepath": "rawdata_path",
    "rawdata_filename": "rawdata_filename",
    "sourcedata_filepath": "sourcedata_path",
    "sourcedata_filename": "sourcedata_filename",
    "size(bytes)": "size(bytes)",
    "hash": "hash",
    "width": "width",
    "height": "height",
    "codec_name": "codec_name",
    "fps": "fps",
    "nb_frames": "nb_frames",
    "duration": "duration",
}


def save_db_format_export(video_info, dataset_config, video_meta_columns):
    if not video_meta_columns:
        return None

    export_data = {}
    for target_col in video_meta_columns:
        source_col = DB_FORMAT_COLUMN_MAP.get(target_col, target_col)
        export_data[target_col] = (
            video_info[source_col] if source_col in video_info.columns else None
        )

    export_df = pd.DataFrame(export_data)
    output_dir = get_dataset_output_dir(dataset_config)
    os.makedirs(output_dir, exist_ok=True)
    export_path = os.path.join(
        output_dir,
        f"DB_FORMAT_{dataset_config['organ']}_{dataset_config['importdate']}.xlsx",
    )
    export_df.to_excel(export_path, index=False)
    return export_path


def get_dataset_video_dirs(video_dir):
    if isinstance(video_dir, (str, os.PathLike)):
        return [str(video_dir)]
    if isinstance(video_dir, (list, tuple)):
        if not video_dir:
            raise ValueError("dataset video_dir list must not be empty.")
        return [str(path) for path in video_dir]
    raise TypeError(
        "dataset video_dir must be a path string or a list of path strings."
    )


def get_dataset_output_dir(dataset_config):
    if dataset_config.get("output_dir"):
        return dataset_config["output_dir"]

    video_dirs = get_dataset_video_dirs(dataset_config["video_dir"])
    if len(video_dirs) == 1:
        return video_dirs[0]
    return os.path.commonpath(video_dirs)


def get_row_video_root(video_info, row_index, dataset_config):
    if "video_root" in video_info.columns:
        video_root = video_info.loc[row_index, "video_root"]
        if not pd.isna(video_root):
            return str(video_root)
    return get_dataset_video_dirs(dataset_config["video_dir"])[0]


def build_video_info(video_dir):
    video_infos = []
    for root_dir in get_dataset_video_dirs(video_dir):
        source_info = get_video_infomation(root_dir)
        source_info["video_root"] = root_dir
        posix = PurePath(root_dir)
        root_info = check_patient_ids(
            source_info,
            root_dir,
            id_path_index=len(posix.parts),
        )
        root_info["video_root"] = root_dir
        video_infos.append(root_info)

    video_info = pd.concat(video_infos, ignore_index=True)
    video_info.insert(0, "hutom_id", None)
    return video_info


def stage_0_load_data(config):
    return load_shared_metadata(
        config,
        [
            ("video_meta", "video_meta"),
            ("hids_all", "hids_all"),
        ],
        verbose=config.get("verbose", False),
    )


def stage_1_extract_base_info(dataset_config):
    video_info = build_video_info(dataset_config["video_dir"])
    video_info[
        [
            "size(bytes)",
            "width",
            "height",
            "codec_name",
            "fps",
            "nb_frames",
            "duration",
            "split",
            "capture_mode",
            "ch_name",
            "sourcedata_path",
            "sourcedata_filename",
            "anony_filepath",
        ]
    ] = None
    video_info["data_type"] = dataset_config["organ"]
    return video_info


def stage_2_extract_metadata(
    video_info,
    dataset_config,
    video_meta,
    next_id,
    n_digits,
    capture=False,
    capture_deinterlace=False,
):
    hash_col = get_hash_column(video_meta)
    ids = video_info["patient_id"].unique().tolist()

    for patient_id in ids:
        check_sample = video_info[video_info["patient_id"] == patient_id]
        check_idx = check_sample.index.tolist()

        capture_mode = infer_capture_mode(check_sample["filepath"].tolist())
        video_info.loc[check_idx, "capture_mode"] = capture_mode

        for row_index in check_idx:
            filepath = check_sample.loc[row_index, "filepath"]
            video_root = get_row_video_root(video_info, row_index, dataset_config)
            save_dir = os.path.join(video_root, "capture")
            meta_ffprobe = get_video_metadata_ffprobe(filepath)
            if not meta_ffprobe:
                video_info.loc[row_index, "format"] = "dameged_file"
                continue

            meta_opencv = get_video_metadata_opencv(filepath)
            video_stream = meta_ffprobe["streams"][0]
            video_info.loc[row_index, "size(bytes)"] = os.path.getsize(filepath)
            video_info.loc[row_index, "width"] = video_stream.get(
                "width", meta_opencv["width"]
            )
            video_info.loc[row_index, "height"] = video_stream.get(
                "height", meta_opencv["height"]
            )
            video_info.loc[row_index, "codec_name"] = video_stream.get("codec_name")
            try:
                video_info.loc[row_index, "fps"] = eval(
                    video_stream.get("avg_frame_rate")
                )
            except Exception:
                video_info.loc[row_index, "fps"] = meta_opencv["fps"]
            video_info.loc[row_index, "nb_frames"] = video_stream.get(
                "nb_frames", meta_opencv["nb_frames"]
            )
            video_info.loc[row_index, "duration"] = float(
                video_stream.get("duration", meta_opencv["duration"])
            )

            if capture:
                frames = capture_key_frames_by_video(
                    filepath,
                    video_root,
                    save_dir,
                    save=capture,
                    deinterlace=capture_deinterlace,
                )
                video_info.loc[row_index, "split"] = check_split_screen(frames)
            else:
                video_info.loc[row_index, "split"] = None

        ch_name_map = assign_stereo_ch_names(video_info.loc[check_idx])
        for row_index, ch_name in ch_name_map.items():
            video_info.loc[row_index, "ch_name"] = ch_name

        existing = video_meta[
            video_meta[hash_col].isin(video_info.loc[check_idx, "hash"].tolist())
        ]
        if len(existing) == 0:
            hutomid = f"{dataset_config['organ']}{next_id:0{n_digits}d}"
            next_id += 1
        else:
            hutomid = existing["hutom_id"].tolist()[0]
        video_info.loc[check_idx, "hutom_id"] = hutomid

    return video_info, next_id


def stage_3_prepare_anonymization(
    video_info, dataset_config, ffmpeg_cmd, video_meta_columns=None
):
    jobs = []

    for row_index in video_info.index:
        filepath = video_info.loc[row_index, "filepath"]
        video_root = get_row_video_root(video_info, row_index, dataset_config)
        hutomid = video_info.loc[row_index, "hutom_id"]
        ch_name = video_info.loc[row_index, "ch_name"]
        anonyid = f"{hutomid}_{ch_name}.mp4"
        anony_folder = os.path.join(video_root, "ANONYMOUS", hutomid)
        anony_filename = os.path.join(anony_folder, anonyid)

        os.makedirs(anony_folder, exist_ok=True)

        run_cmd = ffmpeg_cmd.copy()
        run_cmd[2] = filepath
        run_cmd[-1] = anony_filename

        jobs.append(
            {
                "row_index": row_index,
                "cmd": run_cmd,
                "raw_filepath": filepath,
                "anony_filepath": anony_filename,
            }
        )

        video_info.loc[row_index, "sourcedata_path"] = os.path.join(
            "/Volumes/SourceData",
            dataset_config["organ"],
            "VIDEO",
            hutomid,
        )
        video_info.loc[row_index, "sourcedata_filename"] = anonyid
        video_info.loc[row_index, "anony_filepath"] = str(
            PurePath(*PurePath(anony_filename).parts[2:])
        )

    video_info = video_info.copy()
    video_info["rawdata_path"] = video_info["filepath"].apply(build_rawdata_path)
    video_info["Center"] = dataset_config["center"]
    video_info["ImportDate"] = dataset_config["importdate"]

    output_dir = get_dataset_output_dir(dataset_config)
    os.makedirs(output_dir, exist_ok=True)
    preview_path = os.path.join(
        output_dir,
        f"VIDEO_MATA_{dataset_config['organ']}_{dataset_config['importdate']}.xlsx",
    )
    video_info.to_excel(preview_path, index=False)
    save_db_format_export(video_info, dataset_config, video_meta_columns)

    return video_info, jobs


def stage_4_run_anonymization(jobs, recodec):
    for job in jobs:
        if recodec:
            subprocess.run(job["cmd"], check=True)
        else:
            shutil.copyfile(job["raw_filepath"], job["anony_filepath"])


def process_dataset(dataset_config, shared_data, global_config):
    db_next_id = get_next_hutom_id(
        shared_data["hids_all"],
        dataset_config["organ"],
        global_config["n_digits"],
    )
    next_id = resolve_start_id(dataset_config, db_next_id)

    log(f"[0] loading data for {dataset_config['organ']}", global_config["verbose"])
    if dataset_config.get("start_id") is not None:
        log(
            f"    using configured start_id={next_id} instead of DB next_id={db_next_id}",
            global_config["verbose"],
        )
    video_meta = shared_data["video_meta"]

    log(
        f"[1] extracting base info: {dataset_config['video_dir']}",
        global_config["verbose"],
    )
    video_info = stage_1_extract_base_info(dataset_config)

    log("[2] extracting metadata", global_config["verbose"])
    video_info, next_id = stage_2_extract_metadata(
        video_info,
        dataset_config,
        video_meta,
        next_id,
        global_config["n_digits"],
        global_config["capture"],
        global_config["capture_deinterlace"],
    )

    log("[3] preparing anonymization jobs", global_config["verbose"])
    video_info, jobs = stage_3_prepare_anonymization(
        video_info,
        dataset_config,
        global_config["ffmpeg_cmd"],
        global_config["video_meta_columns"],
    )

    log("[4] running anonymization", global_config["verbose"])
    if global_config["run_anonymization"]:
        stage_4_run_anonymization(jobs, global_config["recodec"])

    return video_info


def run_pipeline(config):
    normalized = normalize_config(config)
    shared_data = stage_0_load_data(normalized)

    results = []
    for dataset_config in normalized["datasets"]:
        results.append(process_dataset(dataset_config, shared_data, normalized))
    return results
