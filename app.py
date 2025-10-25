import requests # 크롤링 기능은 사용하지 않지만 구조 유지를 위해 임포트
from bs4 import BeautifulSoup # 크롤링 기능은 사용하지 않지만 구조 유지를 위해 임포트
from flask import Flask, render_template, request
from datetime import datetime
import os
import re # 괄호 제거를 위해 re 모듈 추가
import json # 🔥 [추가] 환경 변수의 JSON 문자열 파싱을 위해 추가

# 🔥🔥🔥 Firebase Admin SDK 임포트
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db 
# from firebase_admin import firestore # Firestore를 사용할 경우 (옵션)


html = 'miri.html' # 템플릿 파일명 설정

app = Flask(__name__)

# --- 1. 환경 설정 (사용자님의 파일명과 URL) ---
LOCAL_CRED_FILE = "gpsk-eaf81-firebase-adminsdk-fbsvc-8659a9f7ec.json"
LOCAL_DB_URL = 'https://gpsk-eaf81-default-rtdb.firebaseio.com/' 

# ----------------------------------------------------
# 🔥🔥🔥 [수정] Firebase Admin SDK 초기화 (Vercel 안전 로직 적용)
# ----------------------------------------------------

# Vercel 환경 변수에서 값 로드 시도
DB_URL = os.environ.get('FIREBASE_DATABASE_URL')
CREDENTIALS_JSON = os.environ.get('FIREBASE_CREDENTIALS_JSON')
IS_FIREBASE_INITIALIZED = False # 초기화 상태 플래그

try:
    if DB_URL and CREDENTIALS_JSON:
        # 1. Vercel 환경 변수 사용 (배포 환경)
        # JSON 문자열을 Python 딕셔너리로 변환
        cred_info = json.loads(CREDENTIALS_JSON)
        cred = credentials.Certificate(cred_info)
        
        # 환경 변수에서 가져온 DB URL로 초기화
        firebase_admin.initialize_app(cred, {'databaseURL': DB_URL})
        print("DEBUG: Firebase Admin SDK 초기화 완료 (Vercel 환경 변수 사용).")
        IS_FIREBASE_INITIALIZED = True
        
    elif os.path.exists(LOCAL_CRED_FILE):
        # 2. 로컬 파일이 존재할 경우에만 로컬 테스트 환경으로 진입
        # os.path.exists()로 파일을 찾는 시도를 안전하게 처리
        cred = credentials.Certificate(LOCAL_CRED_FILE)
        firebase_admin.initialize_app(cred, {'databaseURL': LOCAL_DB_URL})
        print(f"DEBUG: Firebase Admin SDK 초기화 완료 (로컬 파일 '{LOCAL_CRED_FILE}' 사용).")
        IS_FIREBASE_INITIALIZED = True
    
    else:
        # Vercel 환경이며 환경 변수도 없고, 로컬 파일도 없을 때: 초기화 건너뛰기
        print("WARNING: Firebase Admin SDK가 초기화되지 않았습니다. 환경 변수 또는 로컬 JSON 파일이 누락되었습니다.")


except Exception as e:
    # 파싱 오류나 기타 초기화 오류 발생 시 (환경 변수 값 형식 오류 가능성 높음)
    print(f"FATAL ERROR: Firebase 초기화 중 치명적인 오류 발생: {e}")
    IS_FIREBASE_INITIALIZED = False


# --- 2. 학교명 변환 딕셔너리 ---
SCHOOL_ALIAS_MAP = {
    "대현고": "대현고등학교",
    "강남고": "강남고등학교",
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
# Firebase 데이터 읽기 함수
# ----------------------------------------------------
def fetch_data_from_firebase(school_name, formatted_date):
    """
    Firebase Realtime Database에서 학교 급식 데이터를 가져옵니다.
    """
    if not IS_FIREBASE_INITIALIZED:
        # 초기화 실패 시 DB 접근을 막고 오류 메시지를 반환
        return "데이터 로드 오류: Firebase Admin SDK 초기화에 실패했습니다. Vercel 환경 변수 설정을 확인하세요."
        
    try:
        # 데이터베이스의 루트 참조 (meal_data/{학교명}/{YYYYMMDD})
        ref = db.reference(f'meal_data/{school_name}/{formatted_date}')
        
        # 데이터 가져오기
        meal_data = ref.get()

        if meal_data:
            return meal_data
        else:
            return f"{school_name}의 {formatted_date[:4]}년 {formatted_date[4:6]}월 {formatted_date[6:]}일 급식 정보는 데이터베이스에 없습니다."

    except firebase_admin.exceptions.FirebaseError as e:
        return f"데이터 로드 오류: Firebase API 호출 중 오류 발생. 오류: {e}"
    except Exception as e:
        return f"데이터 로드 중 예상치 못한 오류 발생: {e}"


# --- 3. 백엔드 라우트 설정 (메인 페이지) ---
@app.route('/', methods=['GET'])
def index():
    """초기 페이지 로드."""
    return render_template(html, result=None)


# --- 4. 데이터 요청 처리 ---
@app.route('/scrape', methods=['POST'])
def scrape_data():
    """프론트엔드 입력 처리, Firebase 데이터 가져오기 실행."""

    school_alias = request.form.get('school_name', '').strip()
    target_date_input = request.form.get('date', '').strip()  # 사용자 입력 날짜 (YYYY-MM-DD)

    if not school_alias or not target_date_input:
        return render_template(html, result="학교명과 날짜를 모두 입력해 주세요.", school="오류", date="오류")

    # 날짜 형식 변환 로직 (YYYY-MM-DD -> YYYYMMDD)
    try:
        date_obj = datetime.strptime(target_date_input, '%Y-%m-%d')
        formatted_date_for_db = date_obj.strftime('%Y%m%d')

        # 출력용 날짜 형식 변환 (N월 M일)
        display_date = f"{date_obj.month}월 {date_obj.day}일"

    except ValueError:
        return render_template(html, result="잘못된 날짜 형식입니다. (YYYY-MM-DD 형식 확인)", school="오류", date="오류")

    # 학교명 변환
    full_school_name = get_full_school_name(school_alias)

    # Firebase 데이터 로드 실행
    crawled_data = fetch_data_from_firebase(
        full_school_name,
        formatted_date_for_db
    )

    # 결과 정제 (오류 메시지가 아닌 경우에만 괄호 제거)
    if crawled_data and not crawled_data.startswith("데이터 로드 오류") and not "정보는 데이터베이스에 없습니다" in crawled_data:
        # 정규 표현식: 괄호와 괄호 안의 내용 전체 제거
        crawled_data = re.sub(r'\(.*?\)', '', crawled_data).strip()

    # 결과를 프론트엔드로 전달
    return render_template(html,
                           result=crawled_data,
                           school=full_school_name,
                           date=display_date)


if __name__ == '__main__':
    # 로컬 환경 테스트를 위해 debug=True 설정
    app.run(debug=True)
