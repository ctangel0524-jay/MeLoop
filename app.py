import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 설정 및 시크릿 로드 ---
GSHEETS_CREDENTIALS = st.secrets["gspread_credentials"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
SPREADSHEET_URL = st.secrets["SPREADSHEET_URL"]

# --- 2. 구글 시트 직접 연결 함수 ---
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(GSHEETS_CREDENTIALS, scopes=scopes)
    return gspread.authorize(creds)

# --- 3. 데이터 로드 (분야 컬럼 대응 추가) ---
@st.cache_data(ttl=600)
def load_data():
    try:
        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL).sheet1
        data = sh.get_all_records()
        df = pd.DataFrame(data)
        
        if not df.empty:
            # [추가] '분야' 컬럼이 없으면 '미분류'로 생성
            if '분야' not in df.columns:
                df['분야'] = "미분류"
            
            df['NextReview'] = pd.to_datetime(df['NextReview'], errors='coerce')
            cols_to_fix = ['Level', 'SuccessCount', 'TotalAttempts']
            for col in cols_to_fix:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
                else:
                    df[col] = 0
        
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        # 에러 발생 시 '분야'를 포함한 기본 프레임 반환
        return pd.DataFrame(columns=["분야", "용어", "정의", "Level", "NextReview", "SuccessCount", "TotalAttempts"])

# --- 4. 데이터 저장 함수 ---
def save_data(df):
    try:
        if df is None: return
        save_df = df.copy()
        if not save_df.empty:
            save_df['NextReview'] = save_df['NextReview'].dt.strftime('%Y-%m-%d %H:%M:%S')
            save_df = save_df.fillna("")

        client = get_gspread_client()
        sh = client.open_by_url(SPREADSHEET_URL).sheet1
        data_to_save = [save_df.columns.values.tolist()] + save_df.values.tolist()

        if len(data_to_save) > 0:
            sh.clear()
            sh.update(data_to_save)
            st.cache_data.clear()
            st.toast("✅ 구글 시트에 안전하게 저장되었습니다!")
    except Exception as e:
        st.error(f"❌ 데이터 저장 중 오류 발생: {e}")

# --- 5. 세션 상태 초기화 ---
if "quiz_idx" not in st.session_state: st.session_state.quiz_idx = None
if "ai_feedback" not in st.session_state: st.session_state.ai_feedback = None

# --- 6. 사이드바 및 필터링 (핵심 추가 부분!) ---
with st.sidebar:
    st.title("📊 MeLoop Status")
    
    # 데이터 로드
    raw_df = load_data()
    
    # [추가] 분야 필터링 UI
    st.divider()
    if not raw_df.empty:
        # '분야' 리스트 추출 (중복 제거)
        subject_list = ["전체"] + sorted(raw_df['분야'].unique().tolist())
        selected_subject = st.selectbox("🎯 학습 분야 선택", subject_list)
        
        # 선택된 분야로 데이터 필터링
        if selected_subject != "전체":
            df = raw_df[raw_df['분야'] == selected_subject]
        else:
            df = raw_df
            
        st.metric(f"{selected_subject} 용어 수", len(df))
        due_count = len(df[df['NextReview'] <= datetime.now()])
        st.metric("오늘의 복습 대상", due_count)
    else:
        df = raw_df
        st.info("데이터를 먼저 추가해주세요.")

# --- 7. 메인 화면 ---
st.title(f"메룹(MeLoop) - {selected_subject if not raw_df.empty else ''} 모드 ⚡")

# --- 퀴즈 섹션 ---
st.header("🧠 오늘의 복습 챌린지")

if not df.empty:
    due_df = df[df['NextReview'] <= datetime.now()]
    if st.button("🚀 복습 시작"):
        if not due_df.empty:
            st.session_state.quiz_idx = due_df.sample(n=1).index[0]
        else:
            st.session_state.quiz_idx = df.sample(n=1).index[0]
            st.info("현재 복습 대상이 없습니다. 전체 중 랜덤 모드로 진행합니다.")
        st.session_state.ai_feedback = None
        st.rerun()

    if st.session_state.quiz_idx is not None:
        # 인덱스가 필터링된 데이터에 존재하는지 확인
        if st.session_state.quiz_idx in df.index:
            q_row = df.loc[st.session_state.quiz_idx]
            st.subheader(f"Q. [{q_row['분야']}] '{q_row['용어']}' (Level {int(q_row['Level'])})")
            
            user_ans = st.text_area("답변을 입력하세요:", key="ans_area")

            if st.button("AI 정밀 채점"):
                with st.spinner("AI 감독관 검토 중..."):
                    # 데이터 업데이트 로직 (생략 없이 기존과 동일하게 작동)
                    # ... [중략: AI 채점 로직은 기존과 동일] ...
                    client = Groq(api_key=GROQ_API_KEY)
                    prompt = f"용어: {q_row['용어']}, 정석 정의: {q_row['정의']}, 사용자 답변: {user_ans}. 90점 이상 기준 채점."
                    response = client.chat.completions.create(messages=[{"role":"user","content":prompt}], model="llama-3.3-70b-versatile")
                    feedback = response.choices[0].message.content
                    st.session_state.ai_feedback = feedback
                    
                    # 점수 추출 및 레벨 반영
                    score = 0
                    for line in feedback.split('\n'):
                        if "점수:" in line:
                            score = int(''.join(filter(str.isdigit, line)))
                            break
                    
                    # 로직 반영 (원본 raw_df에 반영해야 저장 시 누락 안 됨)
                    raw_df.at[st.session_state.quiz_idx, 'TotalAttempts'] += 1
                    if score >= 90:
                        raw_df.at[st.session_state.quiz_idx, 'Level'] += 1
                        raw_df.at[st.session_state.quiz_idx, 'SuccessCount'] += 1
                        days = int(2 ** raw_df.at[st.session_state.quiz_idx, 'Level'])
                        raw_df.at[st.session_state.quiz_idx, 'NextReview'] = datetime.now() + timedelta(days=days)
                        st.balloons()
                    else:
                        raw_df.at[st.session_state.quiz_idx, 'Level'] = max(0, raw_df.at[st.session_state.quiz_idx, 'Level'] - 0.5)
                        raw_df.at[st.session_state.quiz_idx, 'NextReview'] = datetime.now() + timedelta(days=1)
                    
                    save_data(raw_df)
        
        if st.session_state.ai_feedback:
            st.markdown(st.session_state.ai_feedback)
            st.info(f"✅ 정석 정의: {df.loc[st.session_state.quiz_idx]['정의']}")

# --- 8. 관리 탭 ---
st.divider()
tab1, tab2, tab3 = st.tabs(["➕ 용어 추가", "⚙️ 전체 편집", "📈 통계"])

with tab1:
    st.subheader("➕ 새로운 지식 등록")
    with st.form("add_new_form", clear_on_submit=True):
        # [추가] 분야 입력
        new_subj = st.selectbox("분야 선택", ["피지컬 AI", "데이터 분석", "영단어", "직접 입력"])
        if new_subj == "직접 입력":
            new_subj = st.text_input("새로운 분야 이름 입력")
            
        word = st.text_input("용어")
        defn = st.text_area("정의")
        
        if st.form_submit_button("저장"):
            if word and defn:
                new_row = {
                    "분야": new_subj, "용어": word, "정의": defn, "Level": 0,
                    "NextReview": datetime.now(), "SuccessCount": 0, "TotalAttempts": 0
                }
                raw_df = pd.concat([raw_df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(raw_df)
                st.success(f"'{word}' 등록 완료!")
                st.rerun()

with tab2:
    # 전체 데이터 편집 (raw_df 사용)
    edited_df = st.data_editor(raw_df, use_container_width=True, num_rows="dynamic", hide_index=True)
    if st.button("변경 사항 저장"):
        save_data(edited_df)
        st.rerun()

with tab3:
    if not df.empty:
        st.bar_chart(df['Level'].value_counts())