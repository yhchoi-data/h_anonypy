from main import infer_pipeline_type


def test_infer_pipeline_type_from_explicit_pipeline_key():
    assert infer_pipeline_type({"pipeline": "dicom"}) == "dicom"
    assert infer_pipeline_type({"pipeline": "video"}) == "video"


def test_infer_pipeline_type_from_db_video_config():
    assert (
        infer_pipeline_type(
            {"metadata_source": {"tables": {"video_meta": "public.video"}}}
        )
        == "video"
    )


def test_infer_pipeline_type_from_db_dicom_config():
    assert (
        infer_pipeline_type(
            {"metadata_source": {"tables": {"image_meta": "public.dicom"}}}
        )
        == "dicom"
    )
