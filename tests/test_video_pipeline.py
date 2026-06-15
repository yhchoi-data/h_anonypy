from pathlib import Path

import pandas as pd

from h_anonypy.video_pipeline import (
    build_video_info,
    get_dataset_output_dir,
    process_dataset,
    resolve_start_id,
    stage_2_extract_metadata,
    stage_3_prepare_anonymization,
)


def test_resolve_start_id_uses_dataset_override():
    assert resolve_start_id({"start_id": 42}, db_next_id=7) == 42
    assert resolve_start_id({"start_id": "42"}, db_next_id=7) == 42
    assert resolve_start_id({}, db_next_id=7) == 7
    assert resolve_start_id({"start_id": None}, db_next_id=7) == 7


def test_process_dataset_uses_configured_start_id(monkeypatch, tmp_path):
    seen = {}
    video_info = pd.DataFrame([{"patient_id": "P001"}])
    dataset_config = {
        "video_dir": str(tmp_path),
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
        "start_id": 42,
    }
    shared_data = {
        "hids_all": pd.DataFrame([{"hutom_id": "COLON0006"}]),
        "video_meta": pd.DataFrame(columns=["hash", "hutom_id"]),
    }
    global_config = {
        "n_digits": 4,
        "verbose": False,
        "capture": False,
        "capture_deinterlace": False,
        "ffmpeg_cmd": ["ffmpeg", "-i", None, None],
        "video_meta_columns": None,
        "run_anonymization": False,
        "recodec": True,
    }

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.stage_1_extract_base_info",
        lambda config: video_info,
    )

    def stage_2_stub(
        video_info_arg,
        dataset_config_arg,
        video_meta_arg,
        next_id,
        n_digits,
        capture=False,
        capture_deinterlace=False,
    ):
        seen["next_id"] = next_id
        return video_info_arg, next_id

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.stage_2_extract_metadata",
        stage_2_stub,
    )
    monkeypatch.setattr(
        "h_anonypy.video_pipeline.stage_3_prepare_anonymization",
        lambda *args, **kwargs: (video_info, []),
    )

    process_dataset(dataset_config, shared_data, global_config)

    assert seen["next_id"] == 42


def test_build_video_info_accepts_video_dir_list(tmp_path):
    root_2025 = tmp_path / "2025"
    root_2026 = tmp_path / "2026"
    raw_2025 = root_2025 / "patient_a" / "clip_2025.mp4"
    raw_2026 = root_2026 / "patient_b" / "clip_2026.mp4"
    raw_2025.parent.mkdir(parents=True)
    raw_2026.parent.mkdir(parents=True)
    raw_2025.write_text("dummy", encoding="utf-8")
    raw_2026.write_text("dummy", encoding="utf-8")

    video_info = build_video_info([str(root_2026), str(root_2025)])

    assert len(video_info) == 2
    assert set(video_info["video_root"]) == {str(root_2025), str(root_2026)}
    assert set(video_info["rawdata_filename"]) == {"clip_2025.mp4", "clip_2026.mp4"}


def test_stage_2_extract_metadata_passes_capture_deinterlace(monkeypatch, tmp_path):
    raw_video = tmp_path / "clip_ch1.mp4"
    raw_video.write_text("dummy", encoding="utf-8")
    video_info = pd.DataFrame(
        [
            {
                "patient_id": "P001",
                "filepath": str(raw_video),
                "rawdata_filename": raw_video.name,
                "hash": "hash-1",
            }
        ]
    )
    video_meta = pd.DataFrame(columns=["hash", "hutom_id"])
    dataset_config = {
        "video_dir": str(tmp_path),
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
    }
    seen = {}

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.get_video_metadata_ffprobe",
        lambda filepath: {
            "streams": [
                {
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                    "avg_frame_rate": "30/1",
                    "nb_frames": "30",
                    "duration": "1.0",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "h_anonypy.video_pipeline.get_video_metadata_opencv",
        lambda filepath: {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "nb_frames": 30,
            "duration": 1.0,
        },
    )
    monkeypatch.setattr(
        "h_anonypy.video_pipeline.check_split_screen", lambda frames: None
    )

    def capture_stub(filepath, basepath, savepath, save=False, deinterlace=False):
        seen["deinterlace"] = deinterlace
        seen["save"] = save
        return ["frame"]

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.capture_key_frames_by_video",
        capture_stub,
    )

    stage_2_extract_metadata(
        video_info,
        dataset_config,
        video_meta,
        next_id=1,
        n_digits=4,
        capture=True,
        capture_deinterlace=True,
    )

    assert seen["deinterlace"] is True


def test_stage_2_extract_metadata_uses_row_video_root(monkeypatch, tmp_path):
    root_2025 = tmp_path / "2025"
    root_2026 = tmp_path / "2026"
    raw_video = root_2025 / "patient_a" / "clip_ch1.mp4"
    raw_video.parent.mkdir(parents=True)
    root_2026.mkdir()
    raw_video.write_text("dummy", encoding="utf-8")
    video_info = pd.DataFrame(
        [
            {
                "patient_id": "P001",
                "filepath": str(raw_video),
                "rawdata_filename": raw_video.name,
                "video_root": str(root_2025),
                "hash": "hash-1",
            }
        ]
    )
    video_meta = pd.DataFrame(columns=["hash", "hutom_id"])
    dataset_config = {
        "video_dir": [str(root_2026), str(root_2025)],
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
    }
    seen = {}

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.get_video_metadata_ffprobe",
        lambda filepath: {
            "streams": [
                {
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264",
                    "avg_frame_rate": "30/1",
                    "nb_frames": "30",
                    "duration": "1.0",
                }
            ]
        },
    )
    monkeypatch.setattr(
        "h_anonypy.video_pipeline.get_video_metadata_opencv",
        lambda filepath: {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "nb_frames": 30,
            "duration": 1.0,
        },
    )
    monkeypatch.setattr(
        "h_anonypy.video_pipeline.check_split_screen", lambda frames: None
    )

    def capture_stub(filepath, basepath, savepath, save=True, deinterlace=False):
        seen["basepath"] = basepath
        seen["savepath"] = savepath
        return ["frame"]

    monkeypatch.setattr(
        "h_anonypy.video_pipeline.capture_key_frames_by_video",
        capture_stub,
    )

    stage_2_extract_metadata(
        video_info,
        dataset_config,
        video_meta,
        next_id=1,
        n_digits=4,
        capture=True,
    )

    assert seen["basepath"] == str(root_2025)
    assert seen["savepath"] == str(root_2025 / "capture")


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


def test_stage_3_prepare_anonymization_supports_video_dir_list(tmp_path):
    root_2025 = tmp_path / "2025"
    root_2026 = tmp_path / "2026"
    root_2025.mkdir()
    root_2026.mkdir()
    raw_2025 = root_2025 / "patient_a" / "clip_2025.mp4"
    raw_2026 = root_2026 / "patient_b" / "clip_2026.mp4"
    raw_2025.parent.mkdir(parents=True)
    raw_2026.parent.mkdir(parents=True)
    raw_2025.write_text("dummy", encoding="utf-8")
    raw_2026.write_text("dummy", encoding="utf-8")

    video_info = pd.DataFrame(
        [
            {
                "filepath": str(raw_2025),
                "video_root": str(root_2025),
                "hutom_id": "COLON0001",
                "ch_name": "ch1_01",
                "hash": "hash-1",
            },
            {
                "filepath": str(raw_2026),
                "video_root": str(root_2026),
                "hutom_id": "COLON0002",
                "ch_name": "ch1_01",
                "hash": "hash-2",
            },
        ]
    )
    dataset_config = {
        "video_dir": [str(root_2026), str(root_2025)],
        "organ": "COLON",
        "center": "CENTER",
        "importdate": "20260417",
    }
    ffmpeg_cmd = ["ffmpeg", "-i", None, None]

    result, jobs = stage_3_prepare_anonymization(video_info, dataset_config, ffmpeg_cmd)

    assert jobs[0]["anony_filepath"].startswith(str(root_2025 / "ANONYMOUS"))
    assert jobs[1]["anony_filepath"].startswith(str(root_2026 / "ANONYMOUS"))
    assert not (root_2025 / "ANONYMOUS").exists()
    assert not (root_2026 / "ANONYMOUS").exists()
    assert (tmp_path / "VIDEO_MATA_COLON_20260417.xlsx").exists()
    assert get_dataset_output_dir(dataset_config) == str(tmp_path)
    assert result.loc[0, "sourcedata_filename"] == "COLON0001_ch1_01.mp4"
    assert result.loc[1, "sourcedata_filename"] == "COLON0002_ch1_01.mp4"


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
