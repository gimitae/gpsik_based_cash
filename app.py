import requests # Although not used for scraping, keeping it for original structure adherence
from bs4 import BeautifulSoup # Although not used for scraping, keeping it for original structure adherence
from flask import Flask, render_template, request
from datetime import datetime
import os
import re  # 괄호 제거를 위해 re 모듈 추가

# 🔥🔥🔥 [새로 추가] Firebase Admin SDK 임포트
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db # Realtime Database를 사용할 경우
# from firebase_admin import firestore # Firestore를 사용할 경우 (옵션)


html = 'miri.html' #여기를 index.html로 바꾸면 미리캔버스 없이 볼 수 있어

app = Flask(__name__)

# ----------------------------------------------------
# 🔥🔥🔥 [새로 추가] Firebase Admin SDK 초기화
# 
# 1. Firebase Console에서 서비스 계정(Service Account)을 생성하고 JSON 파일을 다운로드합니다.
# 2. 이 파일을 프로젝트 루트에 저장하고, 파일명을 아래 'serviceAccountKey.json' 대신 사용하세요.
# 3. 환경 변수 (예: FIREBASE_CREDENTIALS)를 사용하여 JSON 내용을 로드하거나,
#    Vercel 배포 시에는 'FIREBASE_CONFIG'와 같은 환경 변수에 JSON 내용을 Base64 인코딩하여 저장할 수 있습니다.
#    여기서는 로컬 환경에서 가장 간단한 방법인 파일 경로를 사용합니다.
#
# !! 중요: Vercel 환경에서는 이 파일 경로 방식 대신, 환경 변수를 사용하는 것이 더 안전하고 적절합니다.
# ----------------------------------------------------

try:
    # 'serviceAccountKey.json' 파일명은 실제 다운로드한 파일명으로 대체해야 합니다.
    # Vercel 배포 시에는 이 부분을 환경 변수 로직으로 변경하는 것을 강력히 권장합니다.
    cred = credentials.Certificate("serviceAccountKey.json")
    # Realtime Database URL 설정 (콘솔에서 확인)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://gpsk-eaf81-default-rtdb.firebaseio.com/' # 예: 'https://your-project-id.firebaseio.com'
    })
    
    # Firestore를 사용하는 경우:
    # db_firestore = firestore.client()

    print("DEBUG: Firebase Admin SDK 초기화 완료.")

except FileNotFoundError:
    print("ERROR: 'serviceAccountKey.json' 파일을 찾을 수 없습니다. Firebase 연동 없이 실행됩니다.")
except Exception as e:
    print(f"ERROR: Firebase 초기화 중 오류 발생: {e}")


# --- 3. 학교명 변환 딕셔너리 ---
SCHOOL_ALIAS_MAP = {
    "대현고": "대현고등학교",
    "강남고": "강남고등학교",
    # 필요한 학교들을 여기에 추가합니다.
    "신선여고": "신선여자고등학교",
    "홈플공고": "대현고등학교"
}


def get_full_school_name(alias):
    """약칭을 정식 학교명으로 변환하는 함수."""
    if alias in SCHOOL_ALIAS_MAP:
        return SCHOOL_ALIAS_MAP[alias]
    elif alias.endswith("고"):
        return alias + "등학교"
    else:
        return alias

# ----------------------------------------------------
# 🔥🔥🔥 [수정] 크롤링 함수를 Firebase 데이터 읽기 함수로 대체
# ----------------------------------------------------
def fetch_data_from_firebase(school_name, formatted_date):
    """
    Firebase Realtime Database에서 학교명과 YYYYMMDD 형식의 날짜를 사용하여 데이터를 가져옵니다.
    
    데이터 구조 예시 (Realtime DB):
    {
      "meal_data": {
        "대현고등학교": {
          "20250429": "밥, 미역국, 불고기...",
          ...
        },
        "강남고등학교": { ... }
      }
    }
    """
    
    try:
        # 데이터베이스의 루트 참조 (예: 'meal_data'를 루트로 가정)
        ref = db.reference(f'meal_data/{school_name}/{formatted_date}')
        
        # 데이터 가져오기 (Realtime Database)
        meal_data = ref.get()

        if meal_data:
            # 가져온 데이터가 문자열이라고 가정하고 반환
            return meal_data
        else:
            return f"데이터 로드 오류: {school_name}의 {formatted_date} 급식 정보를 Firebase에서 찾을 수 없습니다."

    except firebase_admin.exceptions.FirebaseError as e:
        return f"데이터 로드 오류: Firebase API 호출 중 오류 발생. 오류: {e}"
    except Exception as e:
        return f"데이터 로드 중 예상치 못한 오류 발생: {e}"


# --- 4. 크롤링 설정 및 링크 리스트 (더 이상 사용하지 않지만 구조 유지를 위해 주석 처리) ---
# CRAWL_CONFIG = {...}
# def perform_crawling(school_name, formatted_date, original_date_str):
#     """ (사용하지 않음) """
#     # ... 기존 크롤링 로직 ...
#     return "크롤링 함수는 사용하지 않습니다."


# --- 1. 백엔드 라우트 설정 (메인 페이지) ---
@app.route('/', methods=['GET'])
def index():
    """초기 페이지 로드."""
    return render_template(html, result=None)


# --- 2. 입력 및 5. 결과 출력 처리 ---
@app.route('/scrape', methods=['POST'])
def scrape_data():
    """프론트엔드 입력 처리, 학교명 변환, 날짜 변환, Firebase 데이터 가져오기 실행."""

    school_alias = request.form.get('school_name', '').strip()
    target_date_input = request.form.get('date', '').strip()  # 사용자 입력 날짜 (YYYY-MM-DD)

    if not school_alias or not target_date_input:
        return render_template(html, result="학교명과 날짜를 모두 입력해 주세요.", school="오류", date="오류")

    # 날짜 형식 변환 로직 (YYYY-MM-DD -> YYYYMMDD)
    try:
        date_obj = datetime.strptime(target_date_input, '%Y-%m-%d')
        formatted_date_for_url = date_obj.strftime('%Y%m%d')

        # [수정 1] 출력용 날짜 형식 변환 (N월 M일)
        display_date = f"{date_obj.month}월 {date_obj.day}일"

    except ValueError:
        return render_template(html, result="잘못된 날짜 형식입니다. (YYYY-MM-DD 형식 확인)", school="오류", date="오류")

    # 3. 학교명 변환
    full_school_name = get_full_school_name(school_alias)

    # 4. Firebase 데이터 로드 실행
    # 🔥🔥🔥 [수정] 크롤링 함수 대신 Firebase 데이터 로드 함수 호출
    crawled_data = fetch_data_from_firebase(
        full_school_name,
        formatted_date_for_url
    )

    # [수정 2] 결과에서 괄호() 안의 내용과 괄호 자체를 제거
    if crawled_data and not crawled_data.startswith("데이터 로드 오류"): # 오류 메시지 필터 수정
        # 정규 표현식: \(.*?\): 여는 괄호, 닫는 괄호 및 그 사이의 모든 문자를 찾습니다.
        crawled_data = re.sub(r'\(.*?\)', '', crawled_data).strip()

    # 5. 결과를 프론트엔드로 전달
    return render_template(html,
                           result=crawled_data,
                           school=full_school_name,
                           date=display_date)  # N월 M일 형식의 display_date 사용


if __name__ == '__main__':
    # Flask 앱 실행
    # 로컬 환경 테스트를 위해 debug=True 설정
    app.run(debug=True)
