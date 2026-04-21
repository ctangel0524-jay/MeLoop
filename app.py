import streamlit as st

import pandas as pd

from datetime import datetime, timedelta

from groq import Groq

# [교체] 구글 시트 직접 연결 도구

import gspread

from google.oauth2.service_account import Credentials

# [중요] 서비스 계정 정보를 직접 변수에 담습니다.

 

# 1. 시트 설정

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1t90A1a_ZisDrlDIxTHqcthFpI9Qu510sl5LLdM4b2GU/edit?gid=0#gid=0"

 

# [변경] 금고(secrets.toml)에서 정보를 안전하게 가져옵니다.

GSHEETS_CREDENTIALS = st.secrets["gspread_credentials"]

GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

SPREADSHEET_URL = st.secrets["SPREADSHEET_URL"]

 

# 3. 직접 연결 함수 (st.connection 대신 사용)

def get_gspread_client():

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(GSHEETS_CREDENTIALS, scopes=scopes)

    return gspread.authorize(creds)

 

# [수정] st.cache_data 데코레이터를 추가합니다.

@st.cache_data(ttl=600) # 600초(10분) 동안 데이터를 기억합니다.

def load_data():

    try:

        client = get_gspread_client()

        sh = client.open_by_url(SPREADSHEET_URL).sheet1

        data = sh.get_all_records()

       

        df = pd.DataFrame(data)

       

        # --- 여기서부터 수정 및 추가된 로직입니다 ---

        if not df.empty:

            # 1. [핵심] 글자로 된 날짜를 파이썬이 계산할 수 있는 '시간(datetime)' 객체로 변환

            # errors='coerce'는 형식이 잘못된 데이터가 있어도 에러 대신 빈 값(NaT)으로 처리해주는 안전장치입니다.

            df['NextReview'] = pd.to_datetime(df['NextReview'], errors='coerce')

           

            # 2. 숫자형 데이터들이 글자로 인식되지 않도록 확실히 변환

            cols_to_fix = ['Level', 'SuccessCount', 'TotalAttempts']

            for col in cols_to_fix:

                if col in df.columns:

                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

                else:

                    # 컬럼이 없으면 0으로 채운 새 컬럼 생성

                    df[col] = 0

        # ------------------------------------------

       

        return df

    except Exception as e:

        # 429 에러(과부하)가 나면 사용자에게 친절하게 안내합니다.

        if "429" in str(e):

            st.warning("⚠️ 구글 API 요청이 너무 많습니다. 1분만 기다려주세요.")

        else:

            st.error(f"데이터 로드 실패: {e}")

        return pd.DataFrame(columns=["용어", "정의", "Level", "NextReview", "SuccessCount", "TotalAttempts"])

       

def save_data(df):

    try:

        # 1. 데이터가 비어있는지 확인 (잘못된 데이터로 덮어쓰기 방지)

        if df is None:

            st.error("저장할 데이터가 없습니다.")

            return

 

        # 2. [핵심] 날짜(Timestamp)를 문자열로 변환

        # gspread는 날짜 객체를 인식하지 못해 전송 오류가 발생합니다.

        save_df = df.copy()

        if not save_df.empty:

            # NextReview 컬럼이 날짜 형식이라면 문자열로 변환

            save_df['NextReview'] = save_df['NextReview'].dt.strftime('%Y-%m-%d %H:%M:%S')

            # NaN(빈 값)이 있으면 전송 에러가 날 수 있으므로 빈 문자열로 대체

            save_df = save_df.fillna("")

 

        # 3. 연결 및 저장 시도

        client = get_gspread_client()

        sh = client.open_by_url(SPREADSHEET_URL).sheet1

       

        # 4. 데이터 준비 (헤더 + 내용)

        data_to_save = [save_df.columns.values.tolist()] + save_df.values.tolist()

 

        # 5. [안전 장치] 데이터가 확실히 있을 때만 시트 갱신

        if len(data_to_save) > 0:

            sh.clear()

            sh.update(data_to_save)

           

            # --- [여기서부터가 캐싱 핵심!] ---

            # 저장이 성공했으니, 앱이 기억하고 있는 '옛날 데이터(캐시)'를 삭제합니다.

            # 이렇게 해야 다음에 앱이 켜질 때 구글 시트에서 '새 데이터'를 읽어옵니다.

            st.cache_data.clear()

            # -------------------------------

           

            st.toast("✅ 구글 시트에 안전하게 저장되었습니다!")

       

    except Exception as e:

        # 에러가 나면 화면에 아주 크게 표시합니다.

        st.error(f"❌ 데이터 저장 중 치명적 오류 발생: {e}")

        st.write("에러 상세 정보:", e)

 

# 세션 상태 초기화

if "quiz_idx" not in st.session_state:

    st.session_state.quiz_idx = None

if "ai_feedback" not in st.session_state:

    st.session_state.ai_feedback = None

 

# --- API 키 로드 (Secrets 우선) ---

if "GROQ_API_KEY" in st.secrets:

    api_key = st.secrets["GROQ_API_KEY"]

else:

    api_key = st.sidebar.text_input("Groq API Key를 입력하세요", type="password")

 

# --- 사이드바 설정 ---

with st.sidebar:

    st.title("📊 MeLoop Status")

    if api_key:

        st.success("✅ AI 연결 완료")

   

    df_status = load_data()

    if not df_status.empty:

        st.divider()

        st.metric("전체 학습 용어", len(df_status))

        due_count = len(df_status[df_status['NextReview'] <= datetime.now()])

        st.metric("오늘의 복습 대상", due_count)

 

st.title("메룹(MeLoop) - 하드 트레이닝 ⚡")

df = load_data()

 

# --- 1. 퀴즈 섹션 (상단 고정) ---

st.header("🧠 오늘의 복습 챌린지")

 

if not df.empty:

    due_df = df[df['NextReview'] <= datetime.now()]

    if st.button("🚀 복습 시작"):

        # 문제 선정

        if not due_df.empty:

            st.session_state.quiz_idx = due_df.sample(n=1).index[0]

        else:

            st.session_state.quiz_idx = df.sample(n=1).index[0]

            st.info("현재 복습 대상이 없습니다. 전체 중 랜덤 모드로 진행합니다.")

       

        # 답변창 및 피드백 초기화

        st.session_state.ans_area = ""

        st.session_state.ai_feedback = None

        st.rerun()

 

    if st.session_state.quiz_idx is not None:

        q_row = df.loc[st.session_state.quiz_idx]

        st.subheader(f"Q. '{q_row['용어']}' (Level {int(q_row['Level'])})")

       

        user_ans = st.text_area("답변을 입력하세요 (90점 커트라인):", key="ans_area")

 

        if st.button("AI 정밀 채점"):

            if not api_key:

                st.error("API 키를 설정해주세요.")

            else:

                with st.spinner("AI 감독관이 검토 중..."):

                    try:

                        df.at[st.session_state.quiz_idx, 'TotalAttempts'] += 1

                        client = Groq(api_key=api_key)

                        prompt = f"""

                        당신은 엄격한 기술 시험 감독관입니다.

                        [용어: {q_row['용어']}]에 대한 [정석 정의: {q_row['정의']}]와 [사용자 답변: {user_ans}]를 비교하세요.

                        90점 이상은 핵심 키워드가 완벽히 포함된 경우에만 부여하고, 첫 줄에 '점수: 숫자'를 반드시 포함하세요.

                        """

                        response = client.chat.completions.create(

                            messages=[{"role": "user", "content": prompt}],

                            model="llama-3.3-70b-versatile"

                        )

                        feedback = response.choices[0].message.content

                        st.session_state.ai_feedback = feedback

                       

                        score = 0

                        for line in feedback.split('\n'):

                            if "점수:" in line:

                                score = int(''.join(filter(str.isdigit, line)))

                                break

                       

                        if score >= 90:

                            df.at[st.session_state.quiz_idx, 'Level'] += 1

                            df.at[st.session_state.quiz_idx, 'SuccessCount'] += 1

                            days = int(2 ** df.at[st.session_state.quiz_idx, 'Level'])

                            df.at[st.session_state.quiz_idx, 'NextReview'] = datetime.now() + timedelta(days=days)

                            st.balloons()

                        else:

                            df.at[st.session_state.quiz_idx, 'Level'] = max(0, df.at[st.session_state.quiz_idx, 'Level'] - 0.5)

                            df.at[st.session_state.quiz_idx, 'NextReview'] = datetime.now() + timedelta(days=1)

                        save_data(df)

                    except Exception as e:

                        st.error(f"오류: {e}")

 

        if st.session_state.ai_feedback:

            st.markdown(st.session_state.ai_feedback)

            st.info(f"✅ 정석 정의: {q_row['정의']}")

else:

    st.info("공부할 용어를 먼저 등록해주세요!")

 

# --- 2. 관리 및 대시보드 섹션 (탭 구성) ---

st.divider()

st.header("📊 PMO 리포트 및 관리")

tab1, tab2, tab3, tab4 = st.tabs(["🔥 킬러 용어 Top 5", "➕ 용어 추가", "⚙️ 전체 편집", "📈 통계"])

 

# Tab 1: 킬러 용어 (텍스트 중심)

with tab1:

    if not df.empty:

        df['SuccessRate'] = (df['SuccessCount'] / df['TotalAttempts'] * 100).fillna(0)

        killer_terms = df[df['TotalAttempts'] > 0].nsmallest(5, 'SuccessRate')

       

        if not killer_terms.empty:

            st.subheader("⚠️ 취약 용어 집중 마스터")

            for _, row in killer_terms.iterrows():

                with st.expander(f"🚩 {row['용어']} (성공률: {int(row['SuccessRate'])}% | 시도: {int(row['TotalAttempts'])}회)", expanded=True):

                    st.write(f"**정의:** {row['정의']}")

                    st.progress(int(row['SuccessRate']) / 100)

        else:

            st.info("충분한 퀴즈 데이터가 쌓이면 킬러 용어가 나타납니다.")

    else:

        st.write("데이터가 없습니다.")

 

# Tab 2: 용어 추가 (새로 복구된 부분!)

with tab2:

    st.subheader("➕ 새로운 지식 등록")

    with st.form("add_new_form", clear_on_submit=True):

        word = st.text_input("공부할 용어 (예: Physical AI)")

        defn = st.text_area("나만의 정석 정의")

        if st.form_submit_button("지식 저장소에 추가"):

            if word and defn:

                new_data = {

                    "용어": word, "정의": defn, "Level": 0,

                    "NextReview": datetime.now(), "SuccessCount": 0, "TotalAttempts": 0

                }

                df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)

                save_data(df)

                st.success(f"'{word}' 등록 완료!")

                st.rerun()

            else:

                st.warning("용어와 정의를 모두 입력해주세요.")

 

# Tab 3: 전체 편집

with tab3:

    if not df.empty:

        st.subheader("전체 데이터 수정 및 삭제")

        edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic", hide_index=True)

        if st.button("변경 사항 저장"):

            save_data(edited_df)

            st.success("데이터가 성공적으로 업데이트되었습니다.")

            st.rerun()

    else:

        st.write("편집할 데이터가 없습니다.")

 

# Tab 4: 숙련도 통계

with tab4:

    if not df.empty:

        col1, col2 = st.columns(2)

        with col1:

            st.metric("평균 성공률", f"{df['SuccessRate'].mean():.1f}%")

        with col2:

            st.metric("마스터(Lv3+) 용어", f"{len(df[df['Level'] >= 3])}개")

       

        st.write("지식 레벨 분포")

        st.bar_chart(df['Level'].value_counts())