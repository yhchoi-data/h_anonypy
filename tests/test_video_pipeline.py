from pathlib import Path

import pandas as pd

from h_anonypy.video_pipeline import stage_3_prepare_anonymization


def test_stage_3_prepare_anonymization_uses_hutomid_and_channel_in_filename(tmp_path):
    video_dir = tmp_path / "video"
    video_dir.mkdir()
    raw_video = video_dir / "patient_a" / "clip.mp4"
    raw_video.parent.mkdir(parents=True)
    raw_video.write_text("dummy", encoding="utf-8")

    video_info = pd.DataFrame(
        [
            {
                "filepath": str(raw_video),
                "hutom_id": "COLON0001",
                "ch_name": "ch1_01",
                "hash": "hash-1",
                "center": "CENTER",
                "importdate": "20260417",
            }
        ]
    )
    dataset_config = {
        "video_dir": str(video_dir),
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
    }
    ffmpeg_cmd = ["ffmpeg", "-i", None, None]

    result, jobs = stage_3_prepare_anonymization(video_info, dataset_config, ffmpeg_cmd)

    expected_name = "COLON0001_ch1_01.mp4"
    assert Path(jobs[0]["anony_filepath"]).name == expected_name
    assert result.loc[0, "sourcedata_filename"] == expected_name
    assert result.loc[0, "sourcedata_path"].endswith("/VIDEO/COLON0001")
    assert result.loc[0, "rawdata_path"].endswith("/video/patient_a")


def test_stage_3_prepare_anonymization_saves_db_format_excel(tmp_path):
    video_dir = tmp_path / "video"
    video_dir.mkdir()
    raw_video = video_dir / "patient_a" / "clip.mp4"
    raw_video.parent.mkdir(parents=True)
    raw_video.write_text("dummy", encoding="utf-8")

    video_info = pd.DataFrame(
        [
            {
                "filepath": str(raw_video),
                "hutom_id": "COLON0001",
                "patient_id": "P001",
                "ch_name": "ch1_01",
                "hash": "hash-1",
                "rawdata_filename": "clip.mp4",
                "size(bytes)": 123,
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "fps": 30,
                "nb_frames": 100,
                "duration": 3.3,
                "center": "CENTER",
                "importdate": "20260417",
            }
        ]
    )
    dataset_config = {
        "video_dir": str(video_dir),
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
    }
    ffmpeg_cmd = ["ffmpeg", "-i", None, None]
    video_meta_columns = [
        "hutom id",
        "patient id",
        "rawdata_filepath",
        "rawdata_filename",
        "sourcedata_filepath",
        "sourcedata_filename",
        "size(bytes)",
        "hash",
        "width",
        "height",
        "codec_name",
        "fps",
        "nb_frames",
        "duration",
    ]

    stage_3_prepare_anonymization(
        video_info,
        dataset_config,
        ffmpeg_cmd,
        video_meta_columns=video_meta_columns,
    )

    export_path = video_dir / "DB_FORMAT_COLON_20260417.xlsx"
    export_df = pd.read_excel(export_path)

    assert export_path.exists()
    assert list(export_df.columns) == video_meta_columns
    assert export_df.loc[0, "hutom id"] == "COLON0001"
    assert export_df.loc[0, "patient id"] == "P001"
    assert export_df.loc[0, "rawdata_filepath"].endswith("/video/patient_a")
    assert export_df.loc[0, "sourcedata_filepath"].endswith("/VIDEO/COLON0001")
    assert export_df.loc[0, "sourcedata_filename"] == "COLON0001_ch1_01.mp4"
