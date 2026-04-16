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
        "video_meta_fname": config["video_meta_fname"],
        "id_fname": config["id_fname"],
        "n_digits": config.get("n_digits", 4),
        "recodec": config.get("recodec", True),
        "verbose": config.get("verbose", True),
        "ffmpeg_cmd": config.get("ffmpeg_cmd", DEFAULT_FFMPEG_CMD.copy()),
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


def build_video_info(video_dir):
    source_info = get_video_infomation(video_dir)
    posix = PurePath(video_dir)
    video_info = check_patient_ids(
        source_info,
        video_dir,
        id_path_index=len(posix.parts),
    )
    video_info.insert(0, "hutom_id", None)
    return video_info


def stage_0_load_data(config):
    return {
        "video_meta": pd.read_excel(config["video_meta_fname"]),
        "hids_all": pd.read_excel(config["id_fname"]),
    }


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


def stage_2_extract_metadata(video_info, dataset_config, video_meta, next_id, n_digits):
    save_dir = os.path.join(dataset_config["video_dir"], "capture")
    hash_col = get_hash_column(video_meta)
    ids = video_info["patient_id"].unique().tolist()

    for patient_id in ids:
        check_sample = video_info[video_info["patient_id"] == patient_id]
        check_idx = check_sample.index.tolist()

        capture_mode = infer_capture_mode(check_sample["filepath"].tolist())
        video_info.loc[check_idx, "capture_mode"] = capture_mode

        for row_index in check_idx:
            filepath = check_sample.loc[row_index, "filepath"]
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

            frames = capture_key_frames_by_video(
                filepath, dataset_config["video_dir"], save_dir
            )
            video_info.loc[row_index, "split"] = check_split_screen(frames)

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


def stage_3_prepare_anonymization(video_info, dataset_config, ffmpeg_cmd):
    jobs = []

    for row_index in video_info.index:
        filepath = video_info.loc[row_index, "filepath"]
        hutomid = video_info.loc[row_index, "hutom_id"]
        anonyid = f"{video_info.loc[row_index, 'ch_name']}.mp4"
        anony_folder = os.path.join(dataset_config["video_dir"], "ANONYMOUS", hutomid)
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
            anonyid,
        )
        video_info.loc[row_index, "sourcedata_filename"] = anonyid
        video_info.loc[row_index, "anony_filepath"] = str(
            PurePath(*PurePath(anony_filename).parts[2:])
        )

    video_info = video_info.copy()
    video_info["RAW_PATH"] = video_info["filepath"].apply(
        lambda value: str(PurePath(*PurePath(value).parts[2:]))
    )
    video_info["SOURCE_PATH"] = video_info["anony_filepath"]
    video_info["Hash"] = video_info["hash"]
    video_info["Center"] = dataset_config["center"]
    video_info["ImportDate"] = dataset_config["importdate"]

    preview_path = os.path.join(
        dataset_config["video_dir"],
        f"VIDEO_MATA_{dataset_config['organ']}_{dataset_config['importdate']}.xlsx",
    )
    video_info.to_excel(preview_path, index=False)

    return video_info, jobs


def stage_4_run_anonymization(jobs, recodec):
    for job in jobs:
        if recodec:
            subprocess.run(job["cmd"], check=True)
        else:
            shutil.copyfile(job["raw_filepath"], job["anony_filepath"])


def process_dataset(dataset_config, shared_data, global_config):
    next_id = get_next_hutom_id(
        shared_data["hids_all"],
        dataset_config["organ"],
        global_config["n_digits"],
    )

    log(f"[0] loading data for {dataset_config['organ']}", global_config["verbose"])
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
    )

    log("[3] preparing anonymization jobs", global_config["verbose"])
    video_info, jobs = stage_3_prepare_anonymization(
        video_info,
        dataset_config,
        global_config["ffmpeg_cmd"],
    )

    log("[4] running anonymization", global_config["verbose"])
    stage_4_run_anonymization(jobs, global_config["recodec"])

    return video_info


def run_pipeline(config):
    normalized = normalize_config(config)
    shared_data = stage_0_load_data(normalized)

    results = []
    for dataset_config in normalized["datasets"]:
        results.append(process_dataset(dataset_config, shared_data, normalized))
    return results
