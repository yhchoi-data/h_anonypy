import subprocess
import json
import os
import hashlib
import pandas as pd
import numpy as np
import cv2
import shutil
import re
import ntpath
from pathlib import Path
from pathlib import PurePath


def find_common_path(paths):
    # 경로들을 Path 객체로 변환
    paths = [Path(path) for path in paths]

    # 첫 번째 경로로 초기화
    common_parts = paths[0].parts

    # 모든 경로를 비교하여 공통 부분을 찾기
    for path in paths[1:]:
        common_parts = [
            part
            for part, other_part in zip(common_parts, path.parts)
            if part == other_part
        ]

    # 공통 부분 경로 반환
    return Path(*common_parts)


def find_common_and_diff_parts(path1, path2):
    # Path 객체로 경로 변환
    path1 = Path(path1)
    path2 = Path(path2)

    # 공통 부분 찾기
    common_parts = []
    for p1, p2 in zip(path1.parts, path2.parts):
        if p1 == p2:
            common_parts.append(p1)
        else:
            break

    # 공통 부분 경로
    common_path = Path(*common_parts)

    # 차이 부분
    diff_path1 = Path(
        *path1.parts[len(common_parts) :]
    )  # path1에서 공통 부분을 제외한 나머지
    diff_path2 = Path(
        *path2.parts[len(common_parts) :]
    )  # path2에서 공통 부분을 제외한 나머지

    return common_path, diff_path1, diff_path2


def extract_base(filename: str) -> str:
    stem = PurePath(filename).stem  # 확장자 제거: 'M_..._001_001-1'
    return stem.rsplit("_", 1)[0]


def parse_channel_token(filename: str):
    stem = PurePath(filename).stem.lower()
    match = re.search(r"(^|[^a-z0-9])(ch\d+)(?=[^a-z0-9]|$)", stem)
    if match:
        return match.group(2)
    return None


def infer_capture_mode(filepaths):
    channel_tokens = [parse_channel_token(path) for path in filepaths]
    has_ch1 = any(token == "ch1" for token in channel_tokens)
    has_ch2 = any(token == "ch2" for token in channel_tokens)

    if has_ch1 and has_ch2:
        return "stereo"
    if has_ch1:
        return "mono"
    return "mono_or_stereo"


def _frame_to_phash(frame, hash_size=8, highfreq_factor=4):
    if frame is None:
        return None

    img_size = hash_size * highfreq_factor
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (img_size, img_size), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(gray))
    dct_low = dct[:hash_size, :hash_size]
    median = np.median(dct_low[1:, 1:])
    return dct_low > median


def _phash_distance(hash_a, hash_b):
    if hash_a is None or hash_b is None:
        return 1.0
    return np.mean(hash_a != hash_b)


def _capture_distance(video_a, video_b):
    frames_a = video_a.get("frames") or []
    frames_b = video_b.get("frames") or []
    hashes_a = [_frame_to_phash(frame) for frame in frames_a]
    hashes_b = [_frame_to_phash(frame) for frame in frames_b]

    distances = []
    for hash_a, hash_b in zip(hashes_a, hashes_b):
        if hash_a is None or hash_b is None:
            continue
        distances.append(_phash_distance(hash_a, hash_b))

    if not distances:
        return 1.0
    return float(np.mean(distances))


def _metadata_distance(video_a, video_b):
    distance = 0.0
    weights = 0.0

    for key in ["duration", "nb_frames", "fps"]:
        val_a = video_a.get(key)
        val_b = video_b.get(key)
        if pd.isna(val_a) or pd.isna(val_b):
            continue
        val_a = float(val_a)
        val_b = float(val_b)
        scale = max(abs(val_a), abs(val_b), 1.0)
        distance += abs(val_a - val_b) / scale
        weights += 1.0

    if weights == 0:
        return 0.0
    return distance / weights


def score_stereo_pair(video_a, video_b):
    capture_score = _capture_distance(video_a, video_b)
    metadata_score = _metadata_distance(video_a, video_b)
    return 0.8 * capture_score + 0.2 * metadata_score


def _iter_pairings(items):
    if not items:
        yield []
        return

    first = items[0]
    for i in range(1, len(items)):
        pair = (first, items[i])
        rest = items[1:i] + items[i + 1 :]
        for tail in _iter_pairings(rest):
            yield [pair] + tail


def find_stereo_pairs(video_records):
    records = list(video_records)
    if len(records) < 2 or len(records) % 2 != 0:
        return []

    best_pairs = []
    best_score = None
    for pairs in _iter_pairings(records):
        score = sum(score_stereo_pair(a, b) for a, b in pairs)
        if best_score is None or score < best_score:
            best_score = score
            best_pairs = pairs

    best_pairs = sorted(
        best_pairs,
        key=lambda pair: min(pair[0]["rawdata_filename"], pair[1]["rawdata_filename"]),
    )
    return best_pairs


def _normalize_stereo_records(video_records):
    if isinstance(video_records, pd.DataFrame):
        records = []
        for row_index, row in video_records.iterrows():
            record = row.to_dict()
            record.setdefault("row_index", row_index)
            records.append(record)
        return records

    records = []
    for item in video_records:
        record = dict(item)
        records.append(record)
    return records


def assign_stereo_ch_names(video_records):
    records = _normalize_stereo_records(video_records)
    if not records:
        return {}

    assigned = {}
    channel_counts = {}
    for record in sorted(
        records, key=lambda item: (item["rawdata_filename"], item.get("filepath"))
    ):
        channel = parse_channel_token(record["rawdata_filename"]) or "ch1"
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        assigned[record["row_index"]] = f"{channel}_{channel_counts[channel]:02d}"
    return assigned


def compute_sha256(filepath, fast=True):
    sha256 = hashlib.sha256()
    chunk_size = 8192
    fast_bytes = 1024 * 1024
    with open(filepath, "rb") as f:
        if fast:
            sha256.update(f.read(fast_bytes))
        else:
            while chunk := f.read(chunk_size):
                sha256.update(chunk)
    return sha256.hexdigest()


def get_video_metadata_ffprobe(video_path, ffprobe="ffprobe", timeout=None):
    """
    ffprobe로 비디오 메타데이터를 JSON으로 반환.
    - video_path : 비디오 파일 경로
    - ffprobe    : ffprobe 실행 파일 경로 (미지정 시 PATH에서 검색, 환경변수 FFPROBE도 사용)
    - timeout    : subprocess 실행 타임아웃(초)
    """
    # 0) ffprobe 실행 파일 결정
    exe = ffprobe or os.environ.get("FFPROBE") or "ffprobe"
    exe_path = shutil.which(exe)
    if exe_path is None:
        # (선택) 윈도우의 흔한 설치 위치 후보도 점검
        if os.name == "nt":
            candidates = [
                r"C:\ffmpeg\bin\ffprobe.exe",
                r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
                r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    exe_path = c
                    break
    if exe_path is None:
        raise FileNotFoundError(
            "ffprobe를 찾을 수 없습니다. PATH를 설정하거나 ffprobe의 절대경로를 인자로 전달하세요."
        )

    # 1) 경로 정규화 (한글/공백 OK). 너무 긴 윈도우 경로는 \\?\ 프리픽스 적용(선택)
    vp = os.path.abspath(video_path)
    if (
        os.name == "nt"
        and not vp.startswith("\\\\?\\")
        and re.match(r"^[a-zA-Z]:\\", vp)
    ):
        if len(vp) >= 240:  # 길 때만 적용(필요 없으면 제거해도 됨)
            vp = "\\\\?\\" + vp

    # 2) 커맨드 구성
    cmd = [
        exe_path,
        "-v",
        "error",
        "-show_entries",
        "format:stream",
        "-print_format",
        "json",
        vp,
    ]

    # 3) 실행 (stdout/stderr를 UTF-8로 명시적 디코딩 → 윈도우 cp949 문제 회피)
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )

    return json.loads(res.stdout)


def get_video_metadata_opencv(video_path):

    meta = {}
    cap = cv2.VideoCapture(video_path)

    meta["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    meta["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    meta["nb_frames"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    meta["fps"] = cap.get(cv2.CAP_PROP_FPS)
    meta["frames"] = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if meta["fps"] == 0:
        meta["duration"] = 0
    else:
        meta["duration"] = meta["frames"] / meta["fps"]

    cap.release()

    return meta


def get_video_infomation(base_path):

    video_extensions = {".mp4", ".mpg", ".mts", ".avi"}

    # 결과 저장 리스트
    video_files = []
    video_folders = []
    video_hashes = []

    # 하위 폴더 모두 탐색
    for dirpath, dirnames, filenames in os.walk(base_path):
        dirnames[:] = [dirname for dirname in dirnames if dirname != "ANONYMOUS"]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in video_extensions and not filename.startswith("._"):
                full_path = os.path.join(dirpath, filename)
                video_files.append(full_path)
                video_folders.append(dirpath)
                video_hashes.append(compute_sha256(full_path))

    meta = pd.DataFrame(
        [video_folders, video_files, video_hashes],
        index=["rawdata_path", "filepath", "hash"],
    ).T
    meta.insert(0, "patient_id", None)
    meta.insert(1, "patient_name", None)
    meta["format"] = None

    file_list = meta["filepath"].tolist()
    folder_list = meta["rawdata_path"].tolist()
    for j in range(len(file_list)):
        filepath = file_list[j]
        filefolder = Path(folder_list[j])
        filename = ntpath.basename(filepath)
        meta.loc[j, "patient_id"] = Path(filepath).relative_to(Path(base_path)).parts[0]
        if Path(filefolder).parts[-1] == "Videos":
            meta.loc[j, "patient_name"] = Path(filefolder).parts[-2]
        else:
            meta.loc[j, "patient_name"] = Path(filefolder).parts[-1]
        meta.loc[j, "format"] = os.path.splitext(filename)[1][1:]

    return meta


def check_patient_ids(meta_info, base_dir, id_path_index):
    # ids = video_info['patient_id'].unique().tolist()
    video_info = meta_info.copy()
    video_info.insert(2, "rawdata_filename", None)

    filelist = video_info["filepath"].tolist()
    for i in range(len(filelist)):

        filepath = filelist[i]

        path = Path(filepath)
        video_info.loc[i, "rawdata_filename"] = path.name

    video_info["rawdata_path"] = video_info["rawdata_path"].str.replace(
        base_dir, "/Volumes/RawData/", regex=False
    )
    video_info = video_info.sort_values(["patient_id", "rawdata_filename"]).reset_index(
        drop=True
    )

    return video_info


def safe_capture_last_frame(cap, duration_sec, max_shift=1.0, step=0.1):
    """
    duration_sec에서 max_shift까지 step 간격으로 줄이면서 마지막 프레임 찾기
    """
    for shift in range(0, int(max_shift / step) + 1):
        t = duration_sec - shift * step
        if t <= 0:
            break
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret:
            return t, frame
    return None, None  # 모든 시도 실패


def get_video_duration_sec(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    if fps and total_frames and fps > 0 and total_frames > 0:
        return total_frames / fps

    try:
        meta = get_video_metadata_ffprobe(video_path)
    except Exception:
        return 0

    streams = meta.get("streams") or []
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        streams[0] if streams else {},
    )
    duration = video_stream.get("duration") or meta.get("format", {}).get("duration")
    if duration:
        return float(duration)
    return 0


def capture_frame_by_ffmpeg(
    filepath,
    timestamp_sec,
    deinterlace=False,
    ffmpeg="ffmpeg",
    timeout=30,
    accurate_seek=False,
):
    exe_path = shutil.which(ffmpeg)
    if exe_path is None:
        raise FileNotFoundError(
            "ffmpeg를 찾을 수 없습니다. PATH를 설정하거나 ffmpeg의 절대경로를 전달하세요."
        )

    cmd = [
        exe_path,
        "-v",
        "error",
    ]
    seek_args = ["-ss", f"{max(timestamp_sec, 0):.3f}"]
    if not accurate_seek:
        cmd.extend(seek_args)
    cmd.extend(["-i", filepath])
    if accurate_seek:
        cmd.extend(seek_args)
    cmd.extend(["-map", "0:v:0"])
    if deinterlace:
        cmd.extend(["-vf", "yadif=mode=send_frame:parity=auto:deint=interlaced"])
    cmd.extend(
        [
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ]
    )

    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if res.returncode != 0 or not res.stdout:
        return None

    img_array = np.frombuffer(res.stdout, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)


def _clamp_timestamp(timestamp_sec, duration_sec=None):
    t = max(timestamp_sec, 0)
    if duration_sec and duration_sec > 0:
        t = min(t, max(duration_sec - 0.001, 0))
    return t


def capture_frame_by_ffmpeg_retry(
    filepath,
    timestamp_sec,
    duration_sec=None,
    deinterlace=False,
):
    shifts = [0, 0.05, -0.05, 0.1, -0.1, 0.25, -0.25, 0.5, -0.5, 1.0, -1.0]
    tried = set()

    for accurate_seek in [False, True]:
        for shift in shifts:
            t = _clamp_timestamp(timestamp_sec + shift, duration_sec)
            key = (accurate_seek, round(t, 3))
            if key in tried:
                continue
            tried.add(key)

            frame = capture_frame_by_ffmpeg(
                filepath,
                t,
                deinterlace=deinterlace,
                accurate_seek=accurate_seek,
            )
            if frame is not None:
                return frame
    return None


def safe_capture_last_frame_ffmpeg(
    filepath,
    duration_sec,
    max_shift=1.0,
    step=0.1,
    deinterlace=False,
):
    for shift in range(0, int(max_shift / step) + 1):
        t = duration_sec - shift * step
        if t <= 0:
            break
        frame = capture_frame_by_ffmpeg_retry(
            filepath,
            t,
            duration_sec=duration_sec,
            deinterlace=deinterlace,
        )
        if frame is not None:
            return t, frame
    return None, None


def normalize_capture_frame(frame, target_shape=None):
    if frame is None:
        return None
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    elif frame.ndim != 3 or frame.shape[2] != 3:
        return None

    if target_shape is not None and frame.shape != target_shape:
        target_height, target_width = target_shape[:2]
        frame = cv2.resize(frame, (target_width, target_height))
    return frame


def normalize_capture_frames(frame_list, filepath=None):
    if len(frame_list) != 20:
        raise ValueError(
            f"20개의 capture frame이 필요하지만 {len(frame_list)}개가 생성되었습니다: "
            f"{filepath}"
        )

    frame_list = [normalize_capture_frame(frame) for frame in frame_list]
    valid_indices = [i for i, frame in enumerate(frame_list) if frame is not None]
    if not valid_indices:
        raise ValueError(f"capture frame을 하나도 생성하지 못했습니다: {filepath}")

    target_shape = frame_list[valid_indices[0]].shape
    for i in valid_indices:
        frame_list[i] = normalize_capture_frame(frame_list[i], target_shape)

    valid_indices = [i for i, frame in enumerate(frame_list) if frame is not None]
    missing_indices = [i for i, frame in enumerate(frame_list) if frame is None]
    for i in missing_indices:
        nearest_index = min(valid_indices, key=lambda valid_i: abs(valid_i - i))
        frame_list[i] = frame_list[nearest_index].copy()

    return frame_list


def save_capture_grid(frame_list, out_path):
    imgs_array = np.stack(frame_list)
    frame_height, frame_width, color = frame_list[0].shape
    imgs_array = imgs_array.reshape(4, 5, frame_height, frame_width, color)
    rows = [np.hstack([imgs_array[i, j] for j in range(5)]) for i in range(4)]
    big_img = np.vstack(rows)
    cv2.imwrite(out_path, big_img)


def capture_key_frames_by_video(
    filepath,
    basepath,
    savepath,
    save=True,
    deinterlace=False,
):

    _, _, diffpath = find_common_and_diff_parts(basepath, filepath)
    savepath = Path(savepath)

    if len(diffpath.parts) > 1:
        # savepath = os.path.join(savepath, diffpath.parts[0])
        savepath = savepath / Path(*diffpath.parts[:-1])

    if save:
        os.makedirs(savepath, exist_ok=True)

    filename = ntpath.basename(filepath)
    filename_no_ext, ext = os.path.splitext(filename)

    duration_sec = get_video_duration_sec(filepath)
    timestamps = [duration_sec * i / 20 for i in range(19)]
    frame_list = []

    if deinterlace:
        for t in timestamps:
            frame_list.append(
                capture_frame_by_ffmpeg_retry(
                    filepath,
                    t,
                    duration_sec=duration_sec,
                    deinterlace=deinterlace,
                )
            )
        last_t, last_frame = safe_capture_last_frame_ffmpeg(
            filepath, duration_sec, max_shift=1.0, step=0.1, deinterlace=deinterlace
        )
    else:
        cap = cv2.VideoCapture(filepath)
        for t in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            frame_list.append(frame)
        # 마지막 프레임 안전하게 찾기
        last_t, last_frame = safe_capture_last_frame(
            cap, duration_sec, max_shift=1.0, step=0.1
        )
        cap.release()

    frame_list.append(last_frame)
    frame_list = normalize_capture_frames(frame_list, filepath)
    #
    if save:
        out_path = os.path.join(savepath, filename_no_ext) + "_capture.jpg"
        save_capture_grid(frame_list, out_path)

    return frame_list


def get_image_edge(img, low_thr=15, high_thr=25):

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, low_thr, high_thr)
    return edges


def find_continuous_segments(arr, threshold=100, ratio=0.2):
    arr = np.array(arr)
    length = len(arr)
    mask = arr > threshold

    # 경계점 찾기
    diff = np.diff(mask.astype(int))
    starts = np.where(diff == 1)[0] + 1
    ends = np.where(diff == -1)[0]

    # 예외: 시작부터 True인 경우
    if mask[0]:
        starts = np.insert(starts, 0, 0)
    # 예외: 끝까지 True인 경우
    if mask[-1]:
        ends = np.append(ends, len(arr) - 1)

    segments = []
    for start, end in list(zip(starts, ends)):
        if end - start > length * ratio:
            segments.append((start, end))

    return segments


def is_split_screen(image, threshold=100, ratio=0.2):

    edge = get_image_edge(image)
    vertical_check = edge.max(0)
    horizontal_check = edge.max(1)

    view_vertical = find_continuous_segments(vertical_check, threshold, ratio)
    view_horizontal = find_continuous_segments(horizontal_check, threshold, ratio)

    return view_vertical, view_horizontal


def check_split_screen(frames):

    check_split = [is_split_screen(frame) for frame in frames]
    changes = []
    prev_len = None
    for i, (a, b) in enumerate(check_split):
        current_len = len(b)
        if prev_len is not None and current_len != prev_len:
            changes.append(i)  # 이전과 다른 길이가 나타난 지점
        prev_len = current_len

    if len(changes) == 0:  # 전체 구간 > split or not
        v_f = len(check_split[0][0])
        h_f = len(check_split[0][1])

        if h_f == 2:
            check_screen = "horizontal"
        elif v_f == 2:
            check_screen = "vertical"
        else:
            check_screen = None

    elif len(changes) > 0:  # 1: 시작 / 끝 부분, 2: 중간 부분
        v_b = len(check_split[changes[0] - 1][0])
        h_b = len(check_split[changes[0] - 1][1])
        v_f = len(check_split[changes[0]][0])
        h_f = len(check_split[changes[0]][1])

        if (h_b == 2) or (h_f == 2):
            check_screen = "horizontal_check"
        elif (v_b == 2) or (v_f == 2):
            check_screen = "vertical_check"
        else:
            check_screen = None

    return check_screen
