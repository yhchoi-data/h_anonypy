from pathlib import Path

import pandas as pd

from h_anonypy.dicom_pipeline import (
    save_dicom_preview_metadata,
    stage_4_assign_ids,
    stage_5_run_anonymization,
)


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


def test_stage_5_run_anonymization_builds_jobs_without_writing_files(tmp_path):
    dicom_dir = tmp_path / "LIVER" / "incoming" / "Liver_Dicom"
    raw_folder = dicom_dir / "patient_a" / "DATA" / "20250725" / "092454" / "7866398" / "EX1" / "SE1"
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

    expected_folder = dicom_dir / "ANONYMOUS" / "LIVER0001" / "DATA" / "20250725" / "092454" / "7866398" / "EX1" / "SE1"
    assert Path(result.loc[0, "anony_folder"]) == expected_folder
    assert jobs[0]["raw_folder"] == str(raw_folder)
    assert not list(expected_folder.iterdir())


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
