import os
import random
import string
import re
from pathlib import Path
from collections import defaultdict
import pydicom
from pydicom.errors import InvalidDicomError


pydicom.config.convert_wrong_length_to_UN = True


def replace_digits(match):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_folder_list(path):
    """
  지정된 경로 내의 폴더 목록을 반환합니다.\

  Args:
    path: 폴더 목록을 가져올 경로 (문자열).

  Returns:
    폴더 이름 목록 (문자열 리스트).
  """
    try:
        items = os.listdir(path)
        folder_list = [
            item
            for item in items
            if os.path.isdir(os.path.join(path, item)) and item != "ANONYMOUS"
        ]
        return folder_list
    except FileNotFoundError:
        print(f"Error: 경로를 찾을 수 없습니다: {path}")
        return []
    except Exception as e:
        print(f"Error: {e}")
        return []


def get_patient_info(dicom_file):
    ds = pydicom.dcmread(dicom_file)
    ds.SpecificCharacterSet = "ISO_IR 192"  # UTF-8
    # ds.SpecificCharacterSet = 'ISO_IR 149'  # EUC-KR
    ds.decode()
    info = {
        "PatientID": ds.get("PatientID"),
        "PatientName": str(ds.get("PatientName")),
        "PatientSex": ds.get("PatientSex"),
        "PatientAge": ds.get("PatientAge"),
        "PatientBirthDate": ds.get("PatientBirthDate"),
        "AcquisitionDate": ds.get("AcquisitionDate", "No AcquisitionDate"),
        "StudyDate": ds.get("StudyDate"),
        "SeriesDate": ds.get("SeriesDate"),
        "StudyTime": ds.get("StudyTime"),
        "SeriesTime": ds.get("SeriesTime"),
        "PatientSize": ds.get("PatientSize"),
        "PatientWeight": ds.get("PatientWeight"),
        "OtherPatientIDs": ds.get("OtherPatientIDs"),
        "OtherPatientNames": str(ds.get("OtherPatientNames")),
        "InstitutionName": ds.get("InstitutionName"),
        "ReferringPhysicianName": str(ds.get("ReferringPhysicianName")),
        "AccessionNumber": ds.get("AccessionNumber"),
        "Modality": ds.get("Modality"),
        "BodyPartExamined": ds.get("BodyPartExamined"),
        "StudyInstanceUID": ds.get("StudyInstanceUID"),
        "SeriesInstanceUID": ds.get("SeriesInstanceUID"),
        "SOPInstanceUID": ds.get("SOPInstanceUID"),
        "StudyDescription": ds.get("StudyDescription"),
        "SeriesDescription": ds.get("SeriesDescription"),
        "SeriesNumber": ds.get("SeriesNumber"),
        "InstanceNumber": ds.get("InstanceNumber"),
        "Rows": ds.get("Rows"),
        "Columns": ds.get("Columns"),
        "PixelSpacing": ds.get("PixelSpacing"),
        "SliceThickness": ds.get("SliceThickness"),
    }

    return info


def check_dicom_from_folder(root_dir, return_list=False):
    """
    하위 폴더를 모두 탐색하여 DICOM 존재 여부를 확인한다.

    Args:
        root_dir: 탐색을 시작할 루트 폴더
        return_list: True이면 DICOM 파일이 하나 이상 존재하는 폴더 목록 반환,
            False이면 첫 번째로 찾은 DICOM 파일 경로 반환

    Returns:
        return_list=True: DICOM이 존재하는 폴더 경로 리스트
        return_list=False: 첫 번째 DICOM 파일 경로, 없으면 False
    """
    dcm_dir_list = []

    for dirpath, _, filenames in os.walk(root_dir):
        has_dicom = False
        for file in filenames:
            if file == "DICOMDIR" or file.startswith("._"):
                continue

            filepath = os.path.join(dirpath, file)
            try:
                pydicom.dcmread(filepath, stop_before_pixels=True)
                has_dicom = True
                if not return_list:
                    return filepath
                break
            except InvalidDicomError:
                continue
            except Exception:
                continue

        if return_list and has_dicom:
            dcm_dir_list.append(dirpath)

    if return_list:
        return dcm_dir_list
    return False


def normalize_dicom_filename(filename):
    stem = Path(filename).stem

    # 끝쪽 숫자 시퀀스 제거
    stem = re.sub(r"[_-]?\d+$", "", stem)

    return stem


def group_files_by_filename(root_folder):
    groups = defaultdict(list)

    for dirpath, _, filenames in os.walk(root_folder):
        for fname in filenames:
            if fname == "DICOMDIR" or fname.startswith("._"):
                continue

            key = normalize_dicom_filename(fname)
            filepath = os.path.join(dirpath, fname)
            groups[key].append(filepath)

    return dict(groups)


def get_representative_files_from_dicom_folders(root_folder):
    rep_files = []

    for dirpath, _, filenames in os.walk(root_folder):
        has_dicom = False

        for fname in filenames:
            if fname == "DICOMDIR" or fname.startswith("._"):
                continue

            filepath = os.path.join(dirpath, fname)
            try:
                pydicom.dcmread(filepath, stop_before_pixels=True)
                has_dicom = True
                break
            except InvalidDicomError:
                continue
            except Exception:
                continue

        if has_dicom:
            groups = group_files_by_filename(dirpath)
            rep_files += [sorted(files)[0] for files in groups.values()]
            # dicom_folders.append(dirpath)

    return rep_files


def anonymize_dicom_file(raw_dir, dcm_fname, save_dir, id="00000"):

    # 익명화 대상 태그 정의
    REMOVE_TAGS = [
        (0x0010, 0x0010),  # Patient's Name
        (0x0010, 0x0020),  # Patient ID
        (0x0010, 0x0040),  # Sex
        # (0x0010, 0x1010),  # Patient Age
        (0x0008, 0x0090),  # Referring Physician Name
        (0x0008, 0x0080),  # Institution Name
        (0x0008, 0x0081),  # Institution Address
        (0x0008, 0x1050),  # Performing Physician's Name
        (0x0008, 0x1070),  # Operator's Name
        (0x0010, 0x1000),  # Other Patient IDs
        (0x0010, 0x1001),  # Other Patient Names
        (0x0008, 0x0050),  # Accession Number
    ]

    DATE_TAGS = [
        (0x0008, 0x0020),  # Study Date
        (0x0008, 0x0021),  # Series Date
        (0x0008, 0x0022),  # Acquisition Date
        (0x0008, 0x0023),  # Content Date
        (0x0010, 0x0030),  # Patient's Birth Date
    ]

    try:
        dcm_dir = os.path.join(raw_dir, dcm_fname)
        ds = pydicom.dcmread(dcm_dir)

        # 개인 정보 관련 태그 제거
        for tag in REMOVE_TAGS:
            if tag in ds:
                del ds[tag]
        # 날짜 관련 태그는 연도만 남김
        for tag in DATE_TAGS:
            if tag in ds and ds[tag].value:
                date_str = str(ds[tag].value)  # YYYYMMDD 형태
                year = date_str[:4]  # 연도만 추출
                ds[tag].value = year + "0101"  # 월·일은 01-01로 고정

        # 필수 태그 대체
        ds.PatientName = "anonymous"
        ds.PatientID = id

        # Private Tag 제거
        ds.remove_private_tags()

        # # study uid 확인
        # if len(ds.StudyInstanceUID) > 64:
        #     new_uid, _ = os.path.splitext(ds.StudyInstanceUID)
        #     ds.StudyInstanceUID = new_uid

        # 저장
        _, ext = os.path.splitext(dcm_fname)
        if ext.lower() != ".dcm":
            dcm_fname = dcm_fname + ".dcm"

        ds.save_as(os.path.join(save_dir, dcm_fname))

    except InvalidDicomError:
        print(f"Invalid DICOM: {dcm_dir}")
    except Exception as e:
        print(f"Error processing {dcm_dir}: {e}")
