from main import infer_pipeline_type


def test_infer_pipeline_type_from_explicit_pipeline_key():
    assert infer_pipeline_type({"pipeline": "dicom"}) == "dicom"
    assert infer_pipeline_type({"pipeline": "video"}) == "video"


def test_infer_pipeline_type_from_legacy_video_config():
    assert infer_pipeline_type({"video_meta_fname": "VIDEO_META.xlsx"}) == "video"


def test_infer_pipeline_type_from_legacy_dicom_config():
    assert infer_pipeline_type({"image_meta_fname": "IMAGE_META.xlsx"}) == "dicom"
