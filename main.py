import argparse

from h_anonypy.video_pipeline import load_config, run_pipeline


def build_argparser():
    parser = argparse.ArgumentParser(description="Video anonymization pipeline")
    parser.add_argument("config", help="Path to YAML or JSON config file")
    return parser


def main():
    args = build_argparser().parse_args()
    config = load_config(args.config)
    run_pipeline(config)


if __name__ == "__main__":
    main()
