import json

from h_anonypy.dicom_pipeline import normalize_dicom_config
from h_anonypy.video_pipeline import load_config, normalize_config


def test_load_config_supports_json_and_yaml(tmp_path):
    json_path = tmp_path / "config.json"
    yaml_path = tmp_path / "config.yaml"
    payload = {"pipeline": "video", "datasets": [{"video_dir": "/tmp/video"}]}

    json_path.write_text(json.dumps(payload), encoding="utf-8")
    yaml_path.write_text(
        "pipeline: video\n" "datasets:\n" "  - video_dir: /tmp/video\n",
        encoding="utf-8",
    )

    assert load_config(json_path) == payload
    assert load_config(yaml_path) == payload


def test_normalize_dicom_config_applies_defaults():
    normalized = normalize_dicom_config(
        {
            "image_meta_fname": "IMAGE_META.xlsx",
            "id_fname": "HID_ALL.xlsx",
            "datasets": [
                {
                    "dicom_dir": "/tmp/dicom",
                    "center": "A",
                    "importdate": "20260416",
                    "organ": "LIVER",
                }
            ],
        }
    )

    assert normalized["n_digits"] == 4
    assert normalized["run_anonymization"] is True
    assert normalized["verbose"] is True


def test_normalize_video_config_applies_defaults():
    normalized = normalize_config(
        {
            "video_meta_fname": "VIDEO_META.xlsx",
            "id_fname": "HID_ALL.xlsx",
            "datasets": [
                {
                    "video_dir": "/tmp/video",
                    "center": "A",
                    "importdate": "20260416",
                    "organ": "COLON",
                }
            ],
        }
    )

    assert normalized["n_digits"] == 4
    assert normalized["run_anonymization"] is True
    assert normalized["recodec"] is True
    assert normalized["verbose"] is True
