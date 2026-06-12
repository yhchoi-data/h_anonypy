import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .modules_dicom import (
    anonymize_dicom_file,
    get_folder_list,
    get_patient_info,
    get_representative_files_from_dicom_folders,
)
from .metadata_source import load_shared_metadata, normalize_metadata_source


def load_dicom_config(config_path):
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


def normalize_dicom_config(config):
    datasets = config.get("datasets")
    if not datasets:
        raise ValueError("Config must include a non-empty 'datasets' list.")

    return {
        "metadata_source": normalize_metadata_source(config),
        "n_digits": config.get("n_digits", 4),
        "run_anonymization": config.get("run_anonymization", True),
        "verbose": config.get("verbose", True),
        "datasets": datasets,
    }


def log(message, verbose):
    if verbose:
        print(message)


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


def get_dataset_dicom_dirs(dicom_dir):
    if isinstance(dicom_dir, (str, os.PathLike)):
        return [str(dicom_dir)]
    if isinstance(dicom_dir, (list, tuple)):
        if not dicom_dir:
            raise ValueError("dataset dicom_dir list must not be empty.")
        return [str(path) for path in dicom_dir]
    raise TypeError(
        "dataset dicom_dir must be a path string or a list of path strings."
    )


def get_dataset_output_dir(dataset_config):
    if dataset_config.get("output_dir"):
        return dataset_config["output_dir"]

    dicom_dirs = get_dataset_dicom_dirs(dataset_config["dicom_dir"])
    if len(dicom_dirs) == 1:
        return dicom_dirs[0]
    return os.path.commonpath(dicom_dirs)


def get_row_dicom_root(sample_info, row_index, dataset_config):
    if "dicom_root" in sample_info.columns:
        dicom_root = sample_info.loc[row_index, "dicom_root"]
        if not pd.isna(dicom_root):
            return str(dicom_root)
    return get_dataset_dicom_dirs(dataset_config["dicom_dir"])[0]


def _normalize_key(value):
    if value is None:
        return None
    if pd.isna(value):
        return None
    return str(value).strip()


def _find_series_uid_column(image_meta):
    for col in ["series_instance_uid", "SeriesInstanceUID"]:
        if col in image_meta.columns:
            return col
    return None


def _find_patient_id_column(image_meta):
    for col in ["PatientID", "patient_id"]:
        if col in image_meta.columns:
            return col
    return None


def _build_sample_group_key(row):
    patient_id = _normalize_key(row.get("PatientID"))
    if patient_id:
        return patient_id

    sample_name = _normalize_key(row.get("sample_name")) or row.name
    sample_root = _normalize_key(row.get("sample_root"))
    dicom_root = _normalize_key(row.get("dicom_root"))
    root_key = sample_root or dicom_root
    if root_key:
        return f"sample::{root_key}::{sample_name}"
    return f"sample::{sample_name}"


def _relative_path_from_dataset_root(path_value, dataset_root):
    path_obj = Path(path_value)
    root_obj = Path(dataset_root)

    try:
        return path_obj.relative_to(root_obj)
    except ValueError:
        pass

    root_name = root_obj.name
    if root_name in path_obj.parts:
        idx = path_obj.parts.index(root_name)
        return Path(*path_obj.parts[idx + 1 :])

    return Path(path_obj.name)


def _get_organ_root(dicom_dir, organ):
    dicom_path = Path(dicom_dir)
    if organ in dicom_path.parts:
        idx = dicom_path.parts.index(organ)
        return Path(*dicom_path.parts[: idx + 1])
    raise ValueError(f"Could not infer organ root from path: {dicom_dir}")


def stage_0_load_data(config):
    return load_shared_metadata(
        config,
        [
            ("image_meta", "image_meta"),
            ("hids_all", "hids_all"),
        ],
        verbose=config.get("verbose", False),
    )


def stage_1_list_sample_folders(dataset_config):
    records = []
    for dicom_dir in get_dataset_dicom_dirs(dataset_config["dicom_dir"]):
        sample_folders = get_folder_list(dicom_dir)
        for folder in sample_folders:
            records.append(
                {
                    "sample_name": folder,
                    "sample_root": os.path.join(dicom_dir, folder),
                    "dicom_root": dicom_dir,
                }
            )
    return pd.DataFrame.from_records(
        records, columns=["sample_name", "sample_root", "dicom_root"]
    )


def stage_2_extract_sample_metadata(sample_folders, dataset_config):
    records = []

    for _, row in sample_folders.iterrows():
        sample_root = row["sample_root"]
        dicom_root = row.get("dicom_root")
        if dicom_root is None or pd.isna(dicom_root):
            dicom_root = get_dataset_dicom_dirs(dataset_config["dicom_dir"])[0]
        organ_root = _get_organ_root(dicom_root, dataset_config["organ"])
        rep_files = get_representative_files_from_dicom_folders(sample_root)

        for dicom_file in rep_files:
            metadata = get_patient_info(dicom_file)
            raw_folder = os.path.dirname(dicom_file)
            try:
                folder = str(Path(raw_folder).relative_to(organ_root))
            except ValueError:
                folder = str(_relative_path_from_dataset_root(raw_folder, dicom_root))

            metadata["sample_name"] = row["sample_name"]
            metadata["sample_root"] = sample_root
            metadata["dicom_root"] = dicom_root
            metadata["raw_folder"] = raw_folder
            metadata["folder"] = folder
            metadata["representative_dicom"] = dicom_file
            records.append(metadata)

    return pd.DataFrame.from_records(records)


def stage_3_prepare_full_metadata(sample_info, dataset_config):
    sample_info = sample_info.copy()

    if sample_info.empty:
        sample_info.insert(0, "hutom_id", pd.Series(dtype="object"))
        return sample_info

    sample_info.insert(0, "hutom_id", None)
    sample_info["Center"] = dataset_config["center"]
    sample_info["ImportDate"] = dataset_config["importdate"]
    sample_info["data_type"] = dataset_config["organ"]
    sample_info["study_instance_uid"] = sample_info["StudyInstanceUID"]
    sample_info["series_instance_uid"] = sample_info["SeriesInstanceUID"]
    sample_info["sop_instance_uid"] = sample_info["SOPInstanceUID"]

    ordered_cols = [
        "hutom_id",
        "Center",
        "ImportDate",
        "data_type",
        "PatientID",
        "PatientName",
        "PatientSex",
        "PatientAge",
        "PatientBirthDate",
        "AcquisitionDate",
        "StudyDate",
        "SeriesDate",
        "StudyTime",
        "SeriesTime",
        "InstitutionName",
        "AccessionNumber",
        "Modality",
        "BodyPartExamined",
        "StudyDescription",
        "SeriesDescription",
        "SeriesNumber",
        "InstanceNumber",
        "Rows",
        "Columns",
        "PixelSpacing",
        "SliceThickness",
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "study_instance_uid",
        "series_instance_uid",
        "sop_instance_uid",
        "folder",
        "raw_folder",
        "representative_dicom",
        "sample_name",
        "sample_root",
        "dicom_root",
    ]
    existing_cols = [col for col in ordered_cols if col in sample_info.columns]
    remaining_cols = [col for col in sample_info.columns if col not in existing_cols]
    return sample_info[existing_cols + remaining_cols]


def _find_existing_hutom_id(image_meta, sample_rows):
    series_uid_col = _find_series_uid_column(image_meta)
    if series_uid_col:
        series_uids = [
            value
            for value in sample_rows["SeriesInstanceUID"].map(_normalize_key).tolist()
            if value
        ]
        if series_uids:
            matched = image_meta[
                image_meta[series_uid_col].map(_normalize_key).isin(series_uids)
            ]
            if not matched.empty and "hutom_id" in matched.columns:
                return matched["hutom_id"].dropna().astype(str).iloc[0]

    patient_id_col = _find_patient_id_column(image_meta)
    patient_id = _normalize_key(sample_rows["PatientID"].iloc[0])
    if patient_id_col and patient_id:
        matched = image_meta[
            image_meta[patient_id_col].map(_normalize_key) == patient_id
        ]
        if not matched.empty and "hutom_id" in matched.columns:
            return matched["hutom_id"].dropna().astype(str).iloc[0]

    return None


def stage_4_assign_ids(sample_info, image_meta, hids_all, dataset_config, n_digits):
    sample_info = sample_info.copy()
    if sample_info.empty:
        return sample_info

    db_next_id = get_next_hutom_id(hids_all, dataset_config["organ"], n_digits)
    next_id = resolve_start_id(dataset_config, db_next_id)
    sample_info["_group_key"] = sample_info.apply(_build_sample_group_key, axis=1)
    group_keys = sample_info["_group_key"].dropna().unique().tolist()

    for group_key in group_keys:
        patient_rows = sample_info[sample_info["_group_key"] == group_key]
        existing_hutom_id = _find_existing_hutom_id(image_meta, patient_rows)

        if existing_hutom_id:
            hutom_id = existing_hutom_id
        else:
            hutom_id = f"{dataset_config['organ']}{next_id:0{n_digits}d}"
            next_id += 1

        sample_info.loc[patient_rows.index, "hutom_id"] = hutom_id

    return sample_info.drop(columns="_group_key")


def save_dicom_preview_metadata(sample_info, dataset_config):
    output_dir = get_dataset_output_dir(dataset_config)
    os.makedirs(output_dir, exist_ok=True)
    preview_path = os.path.join(
        output_dir,
        f"DICOM_META_{dataset_config['organ']}_{dataset_config['importdate']}.xlsx",
    )
    sample_info.to_excel(preview_path, index=False)
    return preview_path


def stage_5_run_anonymization(sample_info, dataset_config, run_anonymization):
    jobs = []
    sample_info = sample_info.copy()

    if sample_info.empty:
        sample_info["anony_folder"] = pd.Series(dtype="object")
        return sample_info, jobs

    sample_info["anony_folder"] = None
    sample_info["_group_key"] = sample_info.apply(_build_sample_group_key, axis=1)
    group_keys = sample_info["_group_key"].dropna().unique().tolist()

    for group_key in group_keys:
        sample = sample_info[sample_info["_group_key"] == group_key]
        sample_paths = sample["folder"].tolist()
        hutom_ids = sample["hutom_id"].tolist()

        for row_index, sample_path, hutom_id in zip(
            sample.index, sample_paths, hutom_ids
        ):
            dicom_root = get_row_dicom_root(sample_info, row_index, dataset_config)
            save_dir = Path(dicom_root) / "ANONYMOUS"
            dicom_dir_name = Path(dicom_root).name
            organ_root = _get_organ_root(dicom_root, dataset_config["organ"])
            posix = Path(sample_path)
            if dicom_dir_name not in posix.parts:
                continue

            idx = posix.parts.index(dicom_dir_name)
            subpath = Path(hutom_id) / Path(*posix.parts[idx + 2 :])
            anony_path = save_dir / subpath
            os.makedirs(anony_path, exist_ok=True)

            dcm_path = organ_root / posix
            jobs.append(
                {
                    "row_index": row_index,
                    "raw_folder": str(dcm_path),
                    "anony_folder": str(anony_path),
                    "hutom_id": hutom_id,
                }
            )
            sample_info.loc[row_index, "anony_folder"] = str(anony_path)

            if not run_anonymization:
                continue

            for dirpath, _, filenames in os.walk(dcm_path):
                for filename in sorted(filenames):
                    anonymize_dicom_file(
                        dirpath, filename, str(anony_path), id=hutom_id
                    )

    return sample_info.drop(columns="_group_key"), jobs


def process_dicom_dataset(dataset_config, shared_data, global_config):
    log(
        f"[1] listing sample folders: {dataset_config['dicom_dir']}",
        global_config["verbose"],
    )
    sample_folders = stage_1_list_sample_folders(dataset_config)

    log("[2] extracting sample metadata", global_config["verbose"])
    sample_info = stage_2_extract_sample_metadata(sample_folders, dataset_config)

    log("[3] preparing full metadata", global_config["verbose"])
    sample_info = stage_3_prepare_full_metadata(sample_info, dataset_config)

    log("[4] checking duplicates and assigning IDs", global_config["verbose"])
    sample_info = stage_4_assign_ids(
        sample_info,
        shared_data["image_meta"],
        shared_data["hids_all"],
        dataset_config,
        global_config["n_digits"],
    )

    log("[4.5] saving preview metadata", global_config["verbose"])
    save_dicom_preview_metadata(sample_info, dataset_config)

    log("[5] running anonymization", global_config["verbose"])
    sample_info, jobs = stage_5_run_anonymization(
        sample_info,
        dataset_config,
        global_config["run_anonymization"],
    )

    return {"metadata": sample_info, "jobs": jobs}


def run_dicom_pipeline(config):
    normalized = normalize_dicom_config(config)
    shared_data = stage_0_load_data(normalized)

    results = []
    for dataset_config in normalized["datasets"]:
        results.append(process_dicom_dataset(dataset_config, shared_data, normalized))
    return results
