from pathlib import Path

import pandas as pd

from h_anonypy.dicom_pipeline import (
    get_dataset_output_dir,
    resolve_start_id,
    save_dicom_preview_metadata,
    stage_1_list_sample_folders,
    stage_2_extract_sample_metadata,
    stage_4_assign_ids,
    stage_5_run_anonymization,
)


def test_resolve_start_id_uses_dataset_override_for_dicom():
    assert resolve_start_id({"start_id": 42}, db_next_id=7) == 42
    assert resolve_start_id({"start_id": "42"}, db_next_id=7) == 42
    assert resolve_start_id({}, db_next_id=7) == 7
    assert resolve_start_id({"start_id": None}, db_next_id=7) == 7


def test_stage_1_list_sample_folders_accepts_dicom_dir_list(tmp_path):
    root_2025 = tmp_path / "LIVER" / "2025" / "Liver_Dicom"
    root_2026 = tmp_path / "LIVER" / "2026" / "Liver_Dicom"
    (root_2025 / "patient_a").mkdir(parents=True)
    (root_2026 / "patient_b").mkdir(parents=True)

    result = stage_1_list_sample_folders(
        {"dicom_dir": [str(root_2026), str(root_2025)]}
    )

    assert set(result["sample_name"]) == {"patient_a", "patient_b"}
    assert set(result["dicom_root"]) == {str(root_2025), str(root_2026)}


def test_stage_2_extract_sample_metadata_uses_row_dicom_root(monkeypatch, tmp_path):
    dicom_root = tmp_path / "LIVER" / "2025" / "Liver_Dicom"
    sample_root = dicom_root / "patient_a"
    raw_folder = sample_root / "DATA" / "SE1"
    dicom_file = raw_folder / "IMG0001"
    raw_folder.mkdir(parents=True)
    dicom_file.write_text("dummy", encoding="utf-8")
    sample_folders = pd.DataFrame(
        [
            {
                "sample_name": "patient_a",
                "sample_root": str(sample_root),
                "dicom_root": str(dicom_root),
            }
        ]
    )
    dataset_config = {
        "dicom_dir": [str(dicom_root)],
        "organ": "LIVER",
    }

    monkeypatch.setattr(
        "h_anonypy.dicom_pipeline.get_representative_files_from_dicom_folders",
        lambda sample_root_arg: [str(dicom_file)],
    )
    monkeypatch.setattr(
        "h_anonypy.dicom_pipeline.get_patient_info",
        lambda dicom_file_arg: {
            "PatientID": "P001",
            "PatientName": "Name",
            "StudyInstanceUID": "STUDY",
            "SeriesInstanceUID": "SERIES",
            "SOPInstanceUID": "SOP",
        },
    )

    result = stage_2_extract_sample_metadata(sample_folders, dataset_config)

    assert result.loc[0, "dicom_root"] == str(dicom_root)
    assert result.loc[0, "raw_folder"] == str(raw_folder)
    assert result.loc[0, "folder"] == "2025/Liver_Dicom/patient_a/DATA/SE1"


def test_stage_4_assign_ids_reuses_existing_hutom_id_from_series_uid():
    sample_info = pd.DataFrame(
        [
            {
                "PatientID": "P001",
                "SeriesInstanceUID": "SERIES-1",
                "sample_name": "sample_a",
            }
        ]
    )
    image_meta = pd.DataFrame(
        [{"series_instance_uid": "SERIES-1", "hutom_id": "LIVER0042"}]
    )
    hids_all = pd.DataFrame([{"hutom_id": "LIVER0041"}])

    result = stage_4_assign_ids(
        sample_info,
        image_meta,
        hids_all,
        {"organ": "LIVER"},
        4,
    )

    assert result.loc[0, "hutom_id"] == "LIVER0042"


def test_stage_4_assign_ids_uses_configured_start_id():
    sample_info = pd.DataFrame(
        [
            {
                "PatientID": "P001",
                "SeriesInstanceUID": "SERIES-1",
                "sample_name": "sample_a",
            },
            {
                "PatientID": "P002",
                "SeriesInstanceUID": "SERIES-2",
                "sample_name": "sample_b",
            },
        ]
    )
    image_meta = pd.DataFrame(columns=["series_instance_uid", "hutom_id"])
    hids_all = pd.DataFrame([{"hutom_id": "LIVER0006"}])

    result = stage_4_assign_ids(
        sample_info,
        image_meta,
        hids_all,
        {"organ": "LIVER", "start_id": 42},
        4,
    )

    assert result.loc[0, "hutom_id"] == "LIVER0042"
    assert result.loc[1, "hutom_id"] == "LIVER0043"


def test_stage_4_assign_ids_separates_same_sample_name_across_roots():
    sample_info = pd.DataFrame(
        [
            {
                "PatientID": None,
                "SeriesInstanceUID": "SERIES-1",
                "sample_name": "same_name",
                "dicom_root": "/data/2025/Liver_Dicom",
            },
            {
                "PatientID": None,
                "SeriesInstanceUID": "SERIES-2",
                "sample_name": "same_name",
                "dicom_root": "/data/2026/Liver_Dicom",
            },
        ]
    )
    image_meta = pd.DataFrame(columns=["series_instance_uid", "hutom_id"])
    hids_all = pd.DataFrame([{"hutom_id": "LIVER0006"}])

    result = stage_4_assign_ids(
        sample_info,
        image_meta,
        hids_all,
        {"organ": "LIVER", "start_id": 42},
        4,
    )

    assert result.loc[0, "hutom_id"] == "LIVER0042"
    assert result.loc[1, "hutom_id"] == "LIVER0043"


def test_stage_5_run_anonymization_builds_jobs_without_writing_files(tmp_path):
    dicom_dir = tmp_path / "LIVER" / "incoming" / "Liver_Dicom"
    raw_folder = (
        dicom_dir
        / "patient_a"
        / "DATA"
        / "20250725"
        / "092454"
        / "7866398"
        / "EX1"
        / "SE1"
    )
    raw_folder.mkdir(parents=True)
    (raw_folder / "IMG0001").write_text("dummy", encoding="utf-8")

    sample_info = pd.DataFrame(
        [
            {
                "PatientID": "P001",
                "sample_name": "patient_a",
                "folder": "incoming/Liver_Dicom/patient_a/DATA/20250725/092454/7866398/EX1/SE1",
                "hutom_id": "LIVER0001",
            }
        ]
    )
    dataset_config = {
        "dicom_dir": str(dicom_dir),
        "organ": "LIVER",
        "importdate": "20260416",
    }

    result, jobs = stage_5_run_anonymization(
        sample_info,
        dataset_config,
        run_anonymization=False,
    )

    expected_folder = (
        dicom_dir
        / "ANONYMOUS"
        / "LIVER0001"
        / "DATA"
        / "20250725"
        / "092454"
        / "7866398"
        / "EX1"
        / "SE1"
    )
    assert Path(result.loc[0, "anony_folder"]) == expected_folder
    assert jobs[0]["raw_folder"] == str(raw_folder)
    assert not list(expected_folder.iterdir())


def test_stage_5_run_anonymization_supports_dicom_dir_list(tmp_path):
    dicom_root_2025 = tmp_path / "LIVER" / "2025" / "Liver_Dicom"
    dicom_root_2026 = tmp_path / "LIVER" / "2026" / "Liver_Dicom"
    raw_folder_2025 = dicom_root_2025 / "patient_a" / "DATA" / "SE1"
    raw_folder_2026 = dicom_root_2026 / "patient_b" / "DATA" / "SE1"
    raw_folder_2025.mkdir(parents=True)
    raw_folder_2026.mkdir(parents=True)
    (raw_folder_2025 / "IMG0001").write_text("dummy", encoding="utf-8")
    (raw_folder_2026 / "IMG0001").write_text("dummy", encoding="utf-8")
    sample_info = pd.DataFrame(
        [
            {
                "PatientID": "P001",
                "sample_name": "patient_a",
                "dicom_root": str(dicom_root_2025),
                "folder": "2025/Liver_Dicom/patient_a/DATA/SE1",
                "hutom_id": "LIVER0042",
            },
            {
                "PatientID": "P002",
                "sample_name": "patient_b",
                "dicom_root": str(dicom_root_2026),
                "folder": "2026/Liver_Dicom/patient_b/DATA/SE1",
                "hutom_id": "LIVER0043",
            },
        ]
    )
    dataset_config = {
        "dicom_dir": [str(dicom_root_2025), str(dicom_root_2026)],
        "organ": "LIVER",
        "importdate": "20260416",
    }

    result, jobs = stage_5_run_anonymization(
        sample_info,
        dataset_config,
        run_anonymization=False,
    )

    assert jobs[0]["raw_folder"] == str(raw_folder_2025)
    assert jobs[1]["raw_folder"] == str(raw_folder_2026)
    assert result.loc[0, "anony_folder"].startswith(str(dicom_root_2025 / "ANONYMOUS"))
    assert result.loc[1, "anony_folder"].startswith(str(dicom_root_2026 / "ANONYMOUS"))


def test_save_dicom_preview_metadata_uses_expected_filename(tmp_path):
    sample_info = pd.DataFrame([{"hutom_id": "LIVER0001"}])
    dataset_config = {
        "dicom_dir": str(tmp_path),
        "organ": "LIVER",
        "importdate": "20260416",
    }

    preview_path = save_dicom_preview_metadata(sample_info, dataset_config)

    assert Path(preview_path).name == "DICOM_META_LIVER_20260416.xlsx"
    assert Path(preview_path).exists()


def test_save_dicom_preview_metadata_supports_dicom_dir_list(tmp_path):
    root_2025 = tmp_path / "2025" / "Liver_Dicom"
    root_2026 = tmp_path / "2026" / "Liver_Dicom"
    root_2025.mkdir(parents=True)
    root_2026.mkdir(parents=True)
    sample_info = pd.DataFrame([{"hutom_id": "LIVER0001"}])
    dataset_config = {
        "dicom_dir": [str(root_2025), str(root_2026)],
        "organ": "LIVER",
        "importdate": "20260416",
    }

    preview_path = save_dicom_preview_metadata(sample_info, dataset_config)

    assert Path(preview_path) == tmp_path / "DICOM_META_LIVER_20260416.xlsx"
    assert get_dataset_output_dir(dataset_config) == str(tmp_path)
