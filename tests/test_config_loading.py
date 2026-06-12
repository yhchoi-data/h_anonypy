import json

import pytest

from h_anonypy.dicom_pipeline import normalize_dicom_config
from h_anonypy.metadata_source import (
    _get_table_name,
    build_table_queries,
    create_metadata_engine,
)
from h_anonypy.video_pipeline import load_config, normalize_config


def db_metadata_source(**tables):
    return {
        "type": "db",
        "db": {
            "user": "postgres",
            "password": "postgres",
            "host": "127.0.0.1",
            "port": 6543,
            "database": "Hutom",
        },
        "tables": tables,
    }


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
            "metadata_source": db_metadata_source(
                image_meta="hutom_bronze.tbl_dicom_series_metadata",
                hids_all="hutom_bronze.tbl_id_token_linkage",
            ),
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
            "metadata_source": db_metadata_source(
                video_meta="public.tbl_data_import_video",
                hids_all="hutom_bronze.tbl_id_token_linkage",
            ),
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
    assert normalized["run_anonymization"] is False
    assert normalized["recodec"] is True
    assert normalized["verbose"] is True
    assert normalized["capture_deinterlace"] is False


def test_normalize_video_config_accepts_capture_deinterlace():
    normalized = normalize_config(
        {
            "metadata_source": db_metadata_source(
                video_meta="public.tbl_data_import_video",
                hids_all="hutom_bronze.tbl_id_token_linkage",
            ),
            "capture_deinterlace": True,
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

    assert normalized["capture_deinterlace"] is True


def test_normalize_video_config_accepts_db_metadata_source():
    normalized = normalize_config(
        {
            "metadata_source": db_metadata_source(
                video_meta="public.tbl_data_import_video",
                hids_all="hutom_bronze.tbl_id_token_linkage",
            ),
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

    assert normalized["metadata_source"]["type"] == "db"
    assert "video_meta_fname" not in normalized
    assert "id_fname" not in normalized


def test_normalize_video_config_accepts_top_level_db_metadata_source():
    normalized = normalize_config(
        {
            "db": {"url": ("postgresql+psycopg2://postgres:postgres@127.0.0.1/Hutom")},
            "tables": {
                "VIDEO_META": "public.tbl_data_import_video",
                "HUTOM_ID": "hutom_bronze.tbl_id_token_linkage",
            },
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

    assert normalized["metadata_source"]["type"] == "db"
    assert normalized["metadata_source"]["tables"]["VIDEO_META"].startswith("public")


def test_normalize_dicom_config_accepts_db_metadata_source():
    normalized = normalize_dicom_config(
        {
            "metadata_source": {
                "type": "db",
                "db": {
                    "url": ("postgresql+psycopg2://postgres:postgres@127.0.0.1/Hutom")
                },
                "tables": {
                    "image_meta": "hutom_bronze.tbl_dicom_series_metadata",
                    "hids_all": "hutom_bronze.tbl_id_token_linkage",
                },
            },
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

    assert normalized["metadata_source"]["type"] == "db"
    assert "image_meta_fname" not in normalized
    assert "id_fname" not in normalized


def test_normalize_config_requires_db_metadata_source():
    with pytest.raises(KeyError, match="metadata_source"):
        normalize_config(
            {
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


def test_build_table_queries_quotes_qualified_table_names():
    count_sql, select_sql = build_table_queries("hutom_bronze.tbl_id_token_linkage")

    assert (
        count_sql == 'SELECT COUNT(*) AS n FROM "hutom_bronze"."tbl_id_token_linkage"'
    )
    assert select_sql == 'SELECT * FROM "hutom_bronze"."tbl_id_token_linkage"'


def test_create_metadata_engine_prompts_for_null_db_values(monkeypatch):
    answers = iter(["postgres", "127.0.0.1", "6543", "Hutom"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secret")

    engine = create_metadata_engine(
        {
            "db": {
                "driver": "postgresql+psycopg2",
                "user": None,
                "password": None,
                "host": None,
                "port": None,
                "database": None,
            },
            "tables": {},
        }
    )

    assert engine.url.username == "postgres"
    assert engine.url.password == "secret"
    assert engine.url.host == "127.0.0.1"
    assert engine.url.port == 6543
    assert engine.url.database == "Hutom"


def test_get_table_name_prompts_for_null_table_value(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: "hutom_bronze.tbl_id_token_linkage",
    )

    table_name = _get_table_name({"tables": {"hids_all": None}}, "hids_all")

    assert table_name == "hutom_bronze.tbl_id_token_linkage"
