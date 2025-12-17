
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
        common_parts = [part for part, other_part in zip(common_parts, path.parts) if part == other_part]
    
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
    diff_path1 = Path(*path1.parts[len(common_parts):])  # path1에서 공통 부분을 제외한 나머지
    diff_path2 = Path(*path2.parts[len(common_parts):])  # path2에서 공통 부분을 제외한 나머지

    return common_path, diff_path1, diff_path2

def extract_base(filename: str) -> str:
    stem = PurePath(filename).stem   # 확장자 제거: 'M_..._001_001-1'
    return stem.rsplit('_', 1)[0]   

def compute_sha256(filepath, fast=True):
    sha256 = hashlib.sha256()
    chunk_size=8192
    fast_bytes=1024*1024
    with open(filepath, 'rb') as f:
        if fast:
            sha256.update(f.read(fast_bytes))
        else:
            while chunk := f.read(chunk_size):
                sha256.update(chunk)
    return sha256.hexdigest()

def get_video_metadata_ffprobe(video_path, ffprobe='ffprobe', timeout=None):
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
    if os.name == "nt" and not vp.startswith("\\\\?\\") and re.match(r"^[a-zA-Z]:\\", vp):
        if len(vp) >= 240:  # 길 때만 적용(필요 없으면 제거해도 됨)
            vp = "\\\\?\\" + vp

    # 2) 커맨드 구성
    cmd = [exe_path, "-v", "error", "-show_entries", 'format:stream', "-print_format", "json", vp]

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

    meta['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    meta['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    meta['nb_frames'] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    meta['fps'] = cap.get(cv2.CAP_PROP_FPS)
    meta['frames'] = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if meta['fps'] == 0:
        meta['duration'] = 0
    else:
        meta['duration'] = meta['frames'] / meta['fps']

    cap.release()

    return meta

def get_video_infomation(base_path):
    
    video_extensions = {'.mp4', '.mpg', '.mts', '.avi'}

    # 결과 저장 리스트
    video_files = []
    video_folders = []
    video_hashes = []
    
    # 하위 폴더 모두 탐색
    for dirpath, _, filenames in os.walk(base_path):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in video_extensions and not filename.startswith('._'):
                full_path = os.path.join(dirpath, filename)
                video_files.append(full_path)
                video_folders.append(dirpath)
                video_hashes.append(compute_sha256(full_path))

    meta = pd.DataFrame([video_folders, video_files, video_hashes], index=['filefolder','filepath','hash']).T
    meta.insert(0,'patient_id', None)
    meta.insert(1,'patient_name', None)
    meta['format'] = None

    file_list = meta['filepath'].tolist()
    folder_list = meta['filefolder'].tolist()
    for j in range(len(file_list)):
        filepath = file_list[j]
        filefolder = Path(folder_list[j])
        filename = ntpath.basename(filepath)
        if Path(filefolder).parts[-1] == 'Videos':
            meta.loc[j,'patient_id'] = Path(filefolder).parts[-2]
        else:
            meta.loc[j,'patient_id'] = Path(filefolder).parts[-1]
        meta.loc[j,'patient_name'] = extract_base(filename)
        meta.loc[j,'format'] = os.path.splitext(filename)[1][1:]

    return meta

def check_patient_ids(meta_info, base_dir, id_path_index):
    # ids = video_info['patient_id'].unique().tolist()
    video_info = meta_info.copy()
    video_info.insert(2,'relative_filepath', None)

    filelist = video_info['filepath'].tolist()
    for i in range(len(filelist)):

        filepath = filelist[i]

        path = Path(filepath)
        parts = path.parts  
        relative_path = path.relative_to((base_dir))
        patient_name = Path(parts[id_path_index]).stem

        video_info.loc[i,'patient_name'] = patient_name
        video_info.loc[i,'relative_filepath'] = str(relative_path)

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

def capture_key_frames_by_video(filepath, basepath, savepath, save=True):
    
    _, _, diffpath = find_common_and_diff_parts(basepath, filepath)

    if len(diffpath.parts) > 1:
        savepath = os.path.join(savepath, diffpath.parts[0])
        
    if save==True:
        os.makedirs(savepath, exist_ok=True)

    filename = ntpath.basename(filepath)
    filename_no_ext, ext = os.path.splitext(filename)
    
    cap = cv2.VideoCapture(filepath)

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration_sec = total_frames / fps if fps else 0

    # 기본 시점들, 프레임 저장
    timestamps = [duration_sec * i / 20 for i in range(19)]
    frame_list = []
    for i, t in enumerate(timestamps):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        frame_list.append(frame)
    # 마지막 프레임 안전하게 찾기
    last_t, last_frame = safe_capture_last_frame(cap, duration_sec, max_shift=1.0, step=0.1)
    frame_list.append(last_frame)
    # 
    if save==True:
        imgs_array = np.array(frame_list)  
        width, height, color = frame_list[0].shape
        imgs_array = imgs_array.reshape(4, 5, width, height, color)
        rows = [np.hstack([imgs_array[i, j] for j in range(5)]) for i in range(4)]
        big_img = np.vstack(rows)
        out_path = os.path.join(savepath, filename_no_ext) + f"_capture.jpg"
        cv2.imwrite(out_path, big_img)

    cap.release()

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
    for (start, end) in list(zip(starts, ends)):
        if end-start > length*ratio:
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
            changes.append(i)   # 이전과 다른 길이가 나타난 지점
        prev_len = current_len
    
    if len(changes) == 0: # 전체 구간 > split or not
        v_f = len(check_split[0][0])
        h_f = len(check_split[0][1])
        
        if h_f==2:
            check_screen = 'horizontal'
        elif v_f==2:
            check_screen = 'vertical'
        else:
            check_screen = None
    
    elif len(changes) > 0: # 1: 시작 / 끝 부분, 2: 중간 부분
        v_b = len(check_split[changes[0]-1][0])
        h_b = len(check_split[changes[0]-1][1])
        v_f = len(check_split[changes[0]][0])
        h_f = len(check_split[changes[0]][1])
    
        if (h_b==2) or (h_f==2):
            check_screen = 'horizontal_check'
        elif (v_b==2) or (v_f==2):
            check_screen = 'vertical_check'
        else:
            check_screen = None

    return check_screen
