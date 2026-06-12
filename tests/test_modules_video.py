import numpy as np

from h_anonypy.modules_video import capture_key_frames_by_video, normalize_capture_frames


def test_normalize_capture_frames_fills_missing_and_resizes():
    small_frame = np.zeros((2, 2, 3), dtype=np.uint8)
    large_frame = np.ones((4, 4, 3), dtype=np.uint8)
    frame_list = [small_frame] + [None] + [large_frame] + [small_frame] * 17

    frames = normalize_capture_frames(frame_list, filepath="clip.mp4")

    assert len(frames) == 20
    assert all(frame is not None for frame in frames)
    assert all(frame.shape == (2, 2, 3) for frame in frames)
    assert np.array_equal(frames[1], frames[0])


def test_capture_key_frames_by_video_fills_missing_ffmpeg_frames(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_text("dummy", encoding="utf-8")
    frame = np.zeros((2, 2, 3), dtype=np.uint8)

    monkeypatch.setattr("h_anonypy.modules_video.get_video_duration_sec", lambda _: 20)

    def capture_stub(filepath, timestamp_sec, duration_sec=None, deinterlace=False):
        if 5 <= timestamp_sec < 6:
            return None
        return frame

    monkeypatch.setattr(
        "h_anonypy.modules_video.capture_frame_by_ffmpeg_retry",
        capture_stub,
    )
    monkeypatch.setattr(
        "h_anonypy.modules_video.safe_capture_last_frame_ffmpeg",
        lambda *args, **kwargs: (19, frame),
    )

    frames = capture_key_frames_by_video(
        str(video_path),
        str(tmp_path),
        tmp_path / "capture",
        save=False,
        deinterlace=True,
    )

    assert len(frames) == 20
    assert all(frame is not None for frame in frames)
