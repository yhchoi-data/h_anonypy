import argparse

from h_anonypy.dicom_pipeline import run_dicom_pipeline
from h_anonypy.video_pipeline import load_config, run_pipeline


def build_argparser():
    parser = argparse.ArgumentParser(description="Medical data anonymization pipeline")
    parser.add_argument("config", help="Path to YAML or JSON config file")
    return parser


def infer_pipeline_type(config):
    pipeline_type = config.get("pipeline")
    if pipeline_type:
        return str(pipeline_type).strip().lower()

    if "video_meta_fname" in config:
        return "video"
    if "image_meta_fname" in config:
        return "dicom"

    raise ValueError(
        "Could not infer pipeline type from config. "
        "Add `pipeline: video` or `pipeline: dicom`."
    )


def main():
    args = build_argparser().parse_args()
    config = load_config(args.config)
    pipeline_type = infer_pipeline_type(config)

    if pipeline_type == "video":
        run_pipeline(config)
        return
    if pipeline_type == "dicom":
        run_dicom_pipeline(config)
        return

    raise ValueError(
        f"Unsupported pipeline type: {pipeline_type}. " "Use `video` or `dicom`."
    )


if __name__ == "__main__":
    main()
