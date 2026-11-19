from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
import pandas as pd
import pytest

from h_anonypy import dicom_pipeline


def test_ct_export_preserves_template_and_deduplicates_assigned_ids(tmp_path):
    template = tmp_path / "template.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "CT 양식"
    sheet.append(["patient id", "hutom id", "unused"])
    sheet["A1"].fill = PatternFill(fill_type="solid", fgColor="FFFF0000")
    sheet.append(["example", "example", "example"])
    book.save(template)
    book.close()
    original_template = template.read_bytes()
    metadata = pd.DataFrame(
        [
            {
                "hutom_id": "URO0001 ",
                "PatientID": "00123",
                "SeriesInstanceUID": "SERIES1",
            },
            {
                "hutom_id": "URO0001",
                "PatientID": "00123",
                "SeriesInstanceUID": "SERIES2",
            },
            {
                "hutom_id": "URO0002",
                "PatientID": "00123",
                "SeriesInstanceUID": "SERIES3",
            },
            {"hutom_id": None, "PatientID": "missing"},
            {"hutom_id": "  ", "PatientID": "missing"},
        ]
    )
    original_metadata = metadata.copy(deep=True)
    config = {
        "output_dir": str(tmp_path / "out"),
        "organ": "URO",
        "importdate": "20261117",
    }

    output = dicom_pipeline.save_ct_db_format_export(metadata, config, template)

    assert Path(output).name == "DB_FORMAT_URO_20261117.xlsx"
    with pd.ExcelFile(output) as excel:
        result = pd.read_excel(excel, dtype=str)
    assert list(result.columns) == ["patient id", "hutom id", "unused"]
    assert result["hutom id"].tolist() == ["URO0001", "URO0002"]
    assert result["patient id"].tolist() == ["00123", "00123"]
    assert result["unused"].isna().all()
    output_book = load_workbook(output)
    assert output_book.active.title == "CT 양식"
    assert output_book.active["A1"].fill.fgColor.rgb == "FFFF0000"
    output_book.close()
    assert template.read_bytes() == original_template
    pd.testing.assert_frame_equal(metadata, original_metadata)


def test_ct_export_empty_metadata_writes_only_headers(tmp_path):
    config = {"output_dir": str(tmp_path), "organ": "LIVER", "importdate": "20261117"}
    output = dicom_pipeline.save_ct_db_format_export(pd.DataFrame(), config)
    result = pd.read_excel(output)
    assert list(result.columns) == ["hutom id", "patient id"]
    assert result.empty


def test_ct_export_requires_assigned_ids(tmp_path):
    config = {"output_dir": str(tmp_path), "organ": "URO", "importdate": "20261117"}
    with pytest.raises(ValueError, match="assigned hutom_id"):
        dicom_pipeline.save_ct_db_format_export(
            pd.DataFrame([{"PatientID": "001"}]), config
        )


def test_dicom_dataset_exports_both_series_and_unique_ids_without_anonymization(
    tmp_path, monkeypatch
):
    metadata = pd.DataFrame(
        [
            {"hutom_id": "URO0001", "PatientID": "001", "SeriesInstanceUID": "A"},
            {"hutom_id": "URO0001", "PatientID": "001", "SeriesInstanceUID": "B"},
            {"hutom_id": "URO0002", "PatientID": "002", "SeriesInstanceUID": "C"},
        ]
    )
    monkeypatch.setattr(
        dicom_pipeline, "stage_1_list_sample_folders", lambda _: pd.DataFrame()
    )
    monkeypatch.setattr(
        dicom_pipeline, "stage_2_extract_sample_metadata", lambda *_: metadata.copy()
    )
    monkeypatch.setattr(
        dicom_pipeline, "stage_3_prepare_full_metadata", lambda *_: metadata.copy()
    )
    monkeypatch.setattr(
        dicom_pipeline, "stage_4_assign_ids", lambda *_: metadata.copy()
    )
    monkeypatch.setattr(
        dicom_pipeline, "stage_5_run_anonymization", lambda rows, *_: (rows, [])
    )
    monkeypatch.chdir(tmp_path)
    dataset = {
        "dicom_dir": "/unused/URO",
        "output_dir": str(tmp_path / "out"),
        "organ": "URO",
        "importdate": "20261117",
    }
    dicom_pipeline.process_dicom_dataset(
        dataset,
        {"image_meta": pd.DataFrame(), "hids_all": pd.DataFrame()},
        {"verbose": False, "n_digits": 4, "run_anonymization": False},
    )
    preview = pd.read_excel(tmp_path / "out/DICOM_META_URO_20261117.xlsx")
    export = pd.read_excel(tmp_path / "out/DB_FORMAT_URO_20261117.xlsx", dtype=str)
    assert len(preview) == 3
    assert export["hutom id"].tolist() == ["URO0001", "URO0002"]
    assert export["patient id"].tolist() == ["001", "002"]
