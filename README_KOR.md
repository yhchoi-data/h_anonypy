# anonymize_data

의료 영상(Video)과 DICOM 데이터의 가명화를 위한 유틸리티 및 파이프라인입니다.

[English README](README.md)

## 환경 설정

메타데이터는 DB에서 직접 읽으므로 로컬 메타데이터 파일은 필요하지 않습니다.
저장소에서 `main.py`를 실행할 때는 패키지를 editable 모드로 설치할 필요가 없습니다.

이 프로젝트는 [Pixi](https://pixi.prefix.dev/)로 환경을 관리합니다.
Python 3.11, 실행 의존성, FFmpeg는 `pixi.toml`에 정의되어 있고,
정확한 패키지 버전은 `pixi.lock`에 기록됩니다. `anony` 디렉터리에서 실행하세요.

```bash
pixi install --locked
```

개발 환경 설치 및 검사:

```bash
pixi install -e dev --locked
pixi run -e dev test
pixi run -e dev check
```

환경 안에서 명령어를 실행하거나 셸에 진입할 수 있습니다.

```bash
pixi run python --version
pixi shell
```

config의 DB 접속 정보와 테이블명을 `null`로 두면 CLI 실행 중 입력을 요청합니다.
비밀번호 입력 내용은 화면에 표시되지 않습니다.

> DB 접속 정보와 테이블명은 관리자에게 확인한 값을 사용하세요.

## Config 설정

`main.py`는 JSON 설정 파일을 읽습니다.

예제 파일:

- Video JSON: [video.example.json](configs/video.example.json)
- DICOM JSON: [dicom.example.json](configs/dicom.example.json)

아래 기본값은 해당 옵션을 생략했을 때 적용됩니다.
예제 config에서는 일부 선택 기능을 명시적으로 활성화하고 있습니다.

### 파이프라인 옵션

| 옵션 | 적용 대상 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `pipeline` | 공통 | 테이블 키로 판단 | `video` 또는 `dicom`. 생략하면 `video_meta`/`VIDEO_META`가 있을 때 Video를 선택하고, 그렇지 않으면 `image_meta`/`IMAGE_META`로 DICOM을 선택합니다. 두 테이블이 모두 있으면 명시적으로 지정하세요. |
| `metadata_source` | 공통 | 필수 또는 최상위 DB 설정 | DB 접속 정보와 조회할 테이블 설정입니다. 아래 DB 옵션을 참고하세요. |
| `n_digits` | 공통 | `4` | 새 ID의 숫자 부분을 0으로 채울 최소 자릿수입니다. 예: `URO0001`. |
| `run_anonymization` | 공통 | Video: `false`, DICOM: `true` | `true`이면 가명화 결과 파일을 저장합니다. `false`여도 메타데이터 조회, ID 배정, 작업 목록 생성, 메타데이터 파일 저장은 수행합니다. Video의 `capture: true`이면 캡처 이미지도 생성할 수 있습니다. |
| `verbose` | 공통 | `true` | 파이프라인 진행 상황을 출력합니다. |
| `datasets` | 공통 | 필수 | 처리할 데이터셋 작업 목록입니다. 비어 있으면 안 되며, 작성된 순서대로 처리합니다. |
| `recodec` | Video | `true` | `run_anonymization: true`일 때 적용합니다. `true`이면 FFmpeg로 코덱을 변환하고, `false`이면 원본 파일을 복사합니다. 두 방식 모두 같은 경로의 기존 출력 파일을 덮어씁니다. |
| `preserve_aspect_ratio` | Video | `true` | `recodec: true`일 때 적용합니다. `true`이면 원본 비율을 유지하면서 1280×1024 안에 맞추고 남는 공간을 검은 여백으로 채웁니다. `false`이면 여백 없이 1280×1024로 늘이거나 줄이고 픽셀 종횡비를 1:1로 설정합니다. 반드시 boolean을 사용하세요. `recodec: false`이면 적용하지 않으며, 사용자 지정 `ffmpeg_cmd`가 있으면 해당 명령이 우선합니다. |
| `capture` | Video | `false` | 메타데이터 추출 단계에서 JPG 캡처 이미지를 생성합니다. `run_anonymization`과 별개로 동작합니다. |
| `capture_deinterlace` | Video | `false` | `capture: true`일 때, `true`이면 FFmpeg의 `yadif` 필터로 프레임을 캡처합니다. `false`이면 OpenCV를 사용합니다. |
| `ffmpeg_cmd` | Video | 내장 명령어 | 사용자 지정 FFmpeg 인자 목록입니다. 세 번째 항목(인덱스 `2`)은 입력 경로로, 마지막 항목은 출력 경로로 교체되므로 해당 자리에 `null`을 사용합니다. 리사이즈 설정을 포함한 내장 명령어 전체를 대체합니다. 덮어쓰기 옵션 `-y`는 강제로 적용됩니다. |
| `video_meta_columns` | Video | `null` | `DB_FORMAT_<organ>_<importdate>.xlsx`에 저장할 컬럼명을 순서대로 지정합니다. 생략하거나 빈 목록이면 이 추가 파일은 저장하지 않습니다. 알려진 DB 컬럼명은 내부 메타데이터 컬럼과 연결하고, 값이 없는 컬럼은 비워 둡니다. 일반 메타데이터 파일은 별도로 저장합니다. |
| `ct_meta_format` | DICOM | 저장소의 `configs/CT_META_FORMAT.xlsx` | `DB_FORMAT_<organ>_<importdate>.xlsx`를 생성할 Excel 양식입니다. `run_anonymization: false`여도 `DICOM_META`와 함께 저장합니다. `hutom_id`를 `hutom id`에, `PatientID`를 `patient id`에 채우고 같은 `hutom_id`는 첫 행만 남깁니다. ID가 배정되지 않은 행은 제외합니다. 컬럼 순서·시트명·헤더 서식을 유지하며 원본 양식은 변경하지 않습니다. 사용자 지정 상대경로는 실행 디렉터리를 기준으로 해석합니다. |

내장 Video 변환 명령어의 출력 설정:

- 영상: H.264(`libx264`, High profile, level 4.0), `yuv420p`, 1280×1024, 30 fps, 목표 비트레이트 `6962k`
- 오디오: AAC-LC, 48 kHz, 스테레오, 비트레이트 `128k`
- MP4: `+faststart` 적용

예를 들어 1920×1080 영상에서 `preserve_aspect_ratio: true`이면 영상 영역은
1280×720이 되고, 위아래에 각각 152픽셀의 검은 여백을 추가합니다.
`false`이면 원본 비율과 관계없이 1280×1024 전체를 채웁니다.
JSON에서는 따옴표 없는 소문자 `true`/`false`를 사용하세요.

```json
"recodec": true,
"preserve_aspect_ratio": true
```

위 코드는 설정 파일에 추가할 항목의 예시이며, JSON 객체 안에 작성해야 합니다.

### 데이터셋 옵션

| 옵션 | 적용 대상 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `datasets[].video_dir` | Video | 필수 | 입력 데이터셋 루트입니다. 경로 문자열 또는 비어 있지 않은 경로 목록을 사용합니다. 한 작업에 여러 루트를 지정하면 ID 배정을 함께 처리합니다. |
| `datasets[].dicom_dir` | DICOM | 필수 | 입력 데이터셋 루트입니다. 경로 문자열 또는 비어 있지 않은 경로 목록을 사용합니다. 한 작업에 여러 루트를 지정하면 ID 배정을 함께 처리합니다. |
| `datasets[].output_dir` | 공통 | 필수 | 출력 루트입니다. 가명화 파일은 `ANONYMOUS/` 아래에 저장하며, 메타데이터 파일과 Video 캡처도 이 루트를 사용합니다. |
| `datasets[].center` | 공통 | 필수 | 메타데이터의 `Center`에 기록할 데이터 제공 기관 또는 센터명입니다. |
| `datasets[].importdate` | 공통 | 필수 | 메타데이터의 `ImportDate`와 출력 파일명에 사용할 반입 날짜입니다. `"20261116"`처럼 문자열로 지정하세요. |
| `datasets[].organ` | 공통 | 필수 | 메타데이터의 `data_type`과 새 `hutom_id`의 접두사입니다. 예: `URO0001`. DICOM에서는 경로에서 같은 이름의 폴더를 찾아 상대경로의 기준으로도 사용합니다. `organ: URO`이면 `URO` 또는 `RUS_Kidney` 폴더를 인식하며, 정확한 `URO` 폴더가 있으면 우선합니다. |
| `datasets[].start_id` | 공통 | `null` | 새 ID 배정에 사용할 첫 숫자를 양의 정수로 지정합니다. 지정하면 DB에서 계산한 다음 번호보다 우선합니다. 기존 데이터와 매칭된 ID는 계속 재사용합니다. |

### DB 메타데이터 옵션

현재 메타데이터 입력은 DB 조회만 지원합니다.
파이프라인은 해당 테이블을 읽고 처리 결과를 Excel로 내보냅니다.
DB에 결과를 직접 삽입하지는 않습니다.

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `metadata_source.type` | DB 또는 테이블 설정이 있으면 `db` | `db`만 지원합니다. |
| `metadata_source.db` | 필수 | DB 접속 설정 객체입니다. `metadata_source.database`도 사용할 수 있습니다. `metadata_source`를 생략한 경우 최상위에 `db`/`database`와 `tables`를 지정할 수도 있습니다. |
| `metadata_source.db.url` | 미지정 | 전체 SQLAlchemy 접속 URL입니다. 지정하면 아래의 개별 접속 항목보다 우선합니다. |
| `metadata_source.db.driver` | `postgresql+psycopg2` | SQLAlchemy DB 종류 및 드라이버입니다. |
| `metadata_source.db.user` | 생략 또는 `null`이면 입력 요청 | DB 사용자명입니다. `username`도 사용할 수 있습니다. |
| `metadata_source.db.password` | 생략 또는 `null`이면 입력 요청 | DB 비밀번호입니다. `pwd`도 사용할 수 있습니다. 입력 요청 시 화면에 표시되지 않습니다. |
| `metadata_source.db.password_env` | 미지정 | 비밀번호를 읽을 환경변수 이름입니다. `password`가 없거나 `null`이면 사용합니다. `pwd_env`도 사용할 수 있습니다. 사용할 비밀번호를 찾지 못하면 입력을 요청합니다. |
| `metadata_source.db.host` | 생략 또는 `null`이면 입력 요청 | DB 호스트명 또는 주소입니다. |
| `metadata_source.db.port` | 생략 또는 `null`이면 입력 요청 | DB 포트입니다. 정수로 변환하여 사용합니다. |
| `metadata_source.db.database` | 생략 또는 `null`이면 입력 요청 | DB 이름입니다. 접속 설정 객체 안에서 `db` 또는 `name`으로 지정할 수도 있습니다. |
| `metadata_source.tables` | 필수 | 논리적인 테이블 키와 실제 DB 테이블명을 연결합니다. `schema.table` 형식을 사용하며, 스키마를 생략하면 `public`을 사용합니다. 값이 `null`이어도 필수 키는 작성해야 합니다. `null` 값은 실행 중 입력을 요청합니다. |
| `metadata_source.tables.video_meta` | Video에서 필수 | 기존 Video 메타데이터 테이블입니다. `VIDEO_META`도 사용할 수 있습니다. |
| `metadata_source.tables.image_meta` | DICOM에서 필수 | 기존 이미지 메타데이터 테이블입니다. `IMAGE_META`도 사용할 수 있습니다. |
| `metadata_source.tables.hids_all` | 공통 필수 | 다음 ID 번호를 계산할 때 조회하는 기존 ID 연결 테이블입니다. `hutom_id` 또는 `HUTOM_ID`도 사용할 수 있습니다. |

DB 설정 예시:

```json
{
  "metadata_source": {
    "type": "db",
    "db": {
      "driver": "postgresql+psycopg2",
      "user": null,
      "password": null,
      "host": null,
      "port": null,
      "database": null
    },
    "tables": {
      "video_meta": null,
      "image_meta": null,
      "hids_all": null
    }
  }
}
```

접속 정보가 비어 있으면 실행 중 대화형 입력이 필요합니다.
Video에서는 `video_meta`와 `hids_all`, DICOM에서는 `image_meta`와 `hids_all`이 필요합니다.

## 입력 폴더 구조

두 파이프라인은 입력 데이터셋 루트 아래에 샘플별 폴더가 있는 구조를 사용합니다.

```text
data_dir/
  sample_folder/
    data/  # 영상 파일 또는 DICOM 폴더/파일
```

- `data_dir`: `video_dir` 또는 `dicom_dir`로 전달하는 데이터셋 루트
- `sample_folder`: 데이터셋 루트 바로 아래에 있는 개별 증례 또는 환자 폴더
- `data`: 샘플 폴더 내부의 실제 영상 또는 DICOM 데이터

위의 `data/`는 데이터가 있는 위치를 표현한 예시입니다.
Video 예시처럼 파일이 샘플 폴더 바로 아래에 있어도 됩니다.
샘플을 올바르게 탐색할 수 있도록 데이터셋 루트와 샘플 폴더의 계층을 유지하세요.

Video 입력 예시:

```text
video_dir/
  patient_001/
    clip_01.mp4
    clip_02.mp4
  patient_002/
    exam_video.mov
```

DICOM 입력 예시:

```text
dicom_dir/
  patient_001/
    DATA/
      20250725/
        092454/
          7866398/
            EX1/
              SE1/
                IMG0001
                IMG0002
  patient_002/
    DATA/
      ...
```

## 실행 방법

Video 파이프라인:

```bash
pixi run python main.py configs/video.example.json
```

DICOM 파이프라인:

```bash
pixi run python main.py configs/dicom.example.json
```

## 파이프라인 처리 흐름

Video:

1. DB에서 공통 메타데이터를 읽습니다.
2. 원본 영상의 기본 정보를 추출하고, 중복 확인 후 `hutom_id`를 배정합니다.
3. 영상 메타데이터와 캡처 프레임을 추출합니다.
4. 가명화 작업을 준비하고 미리보기 메타데이터를 저장합니다.
5. 가명화 작업을 실행합니다.

DICOM:

1. DB에서 공통 메타데이터를 읽습니다.
2. 입력 경로의 샘플 폴더 목록을 확인합니다.
3. 각 샘플에서 대표 DICOM의 메타데이터를 추출합니다.
4. 중복을 확인하고 `hutom_id`를 배정합니다.
5. 가명화 작업을 실행하고 미리보기 메타데이터를 저장합니다.

DICOM의 메타데이터 저장 단계에서는 시리즈별 전체 정보인
`DICOM_META_<organ>_<importdate>.xlsx`와 ID별 정보인
`DB_FORMAT_<organ>_<importdate>.xlsx`를 함께 생성합니다.
같은 `hutom_id`를 가진 여러 시리즈는 CT 양식 파일에서 한 행으로 저장하고,
전체 미리보기에는 모든 행을 유지합니다.
