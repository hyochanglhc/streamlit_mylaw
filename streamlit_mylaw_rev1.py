# -*- coding: utf-8 -*-
import streamlit as st
from streamlit_option_menu import option_menu
import pandas as pd
import time
import cv2
import pytesseract
import numpy as np
from datetime import datetime
from bs4 import BeautifulSoup as bs
from io import BytesIO
import os, re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.alert import Alert
from selenium.common.exceptions import NoAlertPresentException

# ==================== 설정 ====================
if os.name == 'nt':  # Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
else:  # Linux (Streamlit Cloud)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# ==================== CourtAutomation 클래스 ====================
class CourtAutomation:
    def __init__(self):
        self.driver = self._create_driver()
        self.wait = WebDriverWait(self.driver, 10)

    def _create_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        return webdriver.Chrome(options=options)

    def solve_captcha(self):
        captcha_img_xpath = '//*[@id="mf_ssgoTopMainTab_contents_content1_body_img_captcha"]'
        reload_btn_id = 'mf_ssgoTopMainTab_contents_content1_body_btn_reloadCaptcha'
        answer_box_id = "mf_ssgoTopMainTab_contents_content1_body_ibx_answer"
        search_btn_id = "mf_ssgoTopMainTab_contents_content1_body_btn_srchCs"

        for attempt in range(15):
            if st.session_state.stop_requested: break
            try:
                element = self.wait.until(EC.presence_of_element_located((By.XPATH, captcha_img_xpath)))
                screenshot = element.screenshot_as_png
                img_array = np.frombuffer(screenshot, np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
                
                img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
                img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
                config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'
                text = pytesseract.image_to_string(img, config=config).strip()

                if len(text) == 6 and text.isnumeric():
                    box = self.driver.find_element(By.ID, answer_box_id)
                    box.clear()
                    box.send_keys(text)
                    self.driver.find_element(By.ID, search_btn_id).click()
                    time.sleep(2)
                    try:
                        alert = Alert(self.driver)
                        alert.accept()
                        time.sleep(1)
                    except NoAlertPresentException:
                        return bs(self.driver.page_source, "html.parser")
                
                self.driver.find_element(By.ID, reload_btn_id).click()
                time.sleep(1.5)
            except: continue
        return None

    def navigate_to_search(self, row):
        self.driver.get("https://www.scourt.go.kr/portal/information/events/search/search.jsp")
        self.wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "#contants > iframe")))
        
        Select(self.wait.until(EC.presence_of_element_located((By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_cortCd")))).select_by_visible_text(row['법원'])
        time.sleep(0.5)
        Select(self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_csYr")).select_by_visible_text(str(row['연도']))
        time.sleep(0.5)
        Select(self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_csDvsCd")).select_by_visible_text(row['구분'])
        time.sleep(0.5)        
        serial = self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_ibx_csSerial")
        serial.clear()
        time.sleep(0.5)
        serial.send_keys(str(row['번호']))
        
        name = self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_ibx_btprNm")
        name.clear()
        name.send_keys(row['관계자'])
        time.sleep(0.1)

    def quit(self):
        self.driver.quit()
        
        
# ==================== 파싱 함수들 ====================
def parse_litigation(soup, row):
    # 1. 기본 테이블 찾기
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl:
        return None
    # 2. 기본 정보 파싱 (딕셔너리 컴프리헨션)
    res = {th.get_text(strip=True): td.get_text(strip=True) 
           for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}
    
    tbl_date = soup.find('table', id=lambda x: x and 'rcntDxdyLst' in x)
    date_info = ["기일미지정"] + [""] * 4 # 기본값 설정
    if tbl_date:
        all_tds = tbl_date.find_all('td')
        if all_tds:
            # 5개씩 묶어서 컬럼별로 join
            groups = [all_tds[i:i+5] for i in range(0, len(all_tds), 5)]
            parsed = [','.join(g[idx].get_text(strip=True) for g in groups if len(g) > idx) for idx in range(5)]
            if parsed[0].strip():
                date_info = parsed
            
    # 데이터 병합 및 가공
    res.update({
        '법원': row.get('법원', ''),
        '관계자': row.get('관계자', ''),
        '기일일자': date_info[0],
        '진행경과': date_info[4],
        '사건번호': str(res.get('사건번호', '')).split('[')[0].strip(),
        '사건명': res.get('사건명', '').replace('[전자]', "").strip()
    })    
    # 원고수 및 소송규모 계산
    plaintiff = res.get('원고', '')
    match = re.search(r'외\s*(\d+)명', plaintiff)
    res['원고수'] = int(match.group(1)) + 1 if match else 1
    #res['소송규모'] = '집단' if res['원고수'] > 5 else '개인'
    #res['판결여부'] = '판결' if res.get('종국결과') else '진행중'    
    
    #최근제출서류
    #grd: grid의 약자로 추정하여, [id$="rcntSbmsnDocmtLst_cell_3_1"] >>> #(id)가 ""로 끝나는 element선택
    #mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_contents_ssgoTab1_body_wfRcntSbmsnDocmtLst_grd_rcntSbmsnDocmtLst_cell_3_1
    try:
        #mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_contents_ssgoTab1_body_wfRcntSbmsnDocmtLst_grd_rcntSbmsnDocmtLst_body_table
        tbl2 = soup.find('table', id=lambda x: x and 'rcntSbmsnDocmtLst_body_table' in x)
        res['최근제출서류'] = tbl2.find_all('td')[-1].text     
    except:
        res['최근제출서류'] =""
    
    
    # 기일 관련 추가 계산
    dates = res['기일일자']
    has_date = dates and dates != "기일미지정" # dates 유효하고, 특정 조건(기일미지정)이 아닌 경우를 체크하는 논리 연산
    res['기일차수'] = len(set(dates.split(','))) if has_date else 0 #split을 set으로 하면 중복값제외됨.
    res['최종일자'] = dates.split(',')[-1].strip() if has_date else "기일미지정"        
    return res

def parse_nego(soup, row):    
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl:
        return None    
    res = {th.get_text(strip=True): td.get_text(strip=True) 
           for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}
    
    tbl_date = soup.find('table', id=lambda x: x and 'rcntDxdyLst' in x)
    
    date_info = ["기일미지정"] + [""] * 4 # 기본값 설정
    if tbl_date:
        all_tds = tbl_date.find_all('td')
        if all_tds:
            # 5개씩 묶어서 컬럼별로 join
            groups = [all_tds[i:i+5] for i in range(0, len(all_tds), 5)]
            parsed = [','.join(g[idx].get_text(strip=True) for g in groups if len(g) > idx) for idx in range(5)]
            if parsed[0].strip():
                date_info = parsed
    # 데이터 병합 및 가공
    res.update({
        '법원': row.get('법원', ''),
        '관계자': row.get('관계자', ''),
        '기일일자': date_info[0],
        '진행경과': date_info[4],
        '사건번호': str(res.get('사건번호', '')).split('[')[0].strip(),
        '사건명': res.get('사건명', '').replace('[전자]', "").strip()
    })    
    # 원고수 및 소송규모 계산
    plaintiff = res.get('원고', '')
    match = re.search(r'외\s*(\d+)명', plaintiff)
    res['원고수'] = int(match.group(1)) + 1 if match else 1
    #res['소송규모'] = '집단' if res['원고수'] > 5 else '개인'
    #res['판결여부'] = '판결' if res.get('종국결과') else '진행중'    
    # 기일 관련 추가 계산
    dates = res['기일일자']
    has_date = dates and dates != "기일미지정"
    res['기일차수'] = len(dates.split(',')) if has_date else 0
    res['최종일자'] = dates.split(',')[-1].strip() if has_date else "기일미지정"    
    return res



def parse_detail(driver, row):
    try:
        driver.find_element(By.CSS_SELECTOR, '#mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_tab_ssgoTab2_tabHTML').click()
        time.sleep(1)
        soup = bs(driver.page_source, "html.parser")
        tbody = soup.find('tbody', id=lambda x: x and 'grd_csProgLst_body_tbody' in x)
        rows_data = []
        if tbody:
            for tr in tbody.find_all('tr', class_='grid_body_row'):
                cells = tr.find_all('td')
                if len(cells) >= 2:
                    rows_data.append({'법원': row['법원'], '사건번호': row['사건번호'], '일자': cells[0].get_text(strip=True), '내용': cells[1].get_text(strip=True)})
        return rows_data
    except: return []


def parse_preattach(soup, row):
    """가압류가처분(카단) 전용 파싱"""
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    #tds = [td.get_text(strip=True) for td in tbl.find_all('td')]    
    tbl_map = {th.get_text(strip=True): td.get_text(strip=True)                
                for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}         
    tbl_map['사건번호'] = tbl_map['사건번호'].split('[')[0]
    tbl_map['사건명'] = tbl_map['사건명'].replace('[전자]',"")
    tbl_map.update({
        '법원': row.get('법원', ''),
        '관계자': row.get('관계자', ''),})    
    return tbl_map
    
def parse_payment_order(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    #tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    tbl_map = {th.get_text(strip=True): td.get_text(strip=True)                
                for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}         
    tbl_map['사건번호'] = tbl_map['사건번호'].split('[')[0]
    tbl_map['사건명'] = tbl_map['사건명'].replace('[전자]',"")
    tbl_map.update({
        '법원': row.get('법원', ''),
        '관계자': row.get('관계자', ''),})            
    try:
        tbl1 = soup.find('table', id=lambda x: x and 'reltCsCtt_body_table' in x)
        tbl_map['관련사건'] = tbl1.find_all('td')[1].text     
    except:
        tbl_map['관련사건'] =""
    
    
    return tbl_map
    
# =============================================================================
#     return {
#         '법원': row.get('법원', ''), '사건번호': tds[0], '관계자': row.get('관계자', ''),
#         '사건명': tds[1].replace("[전자]",""),
#         '채권자': tds[2], '채무자': tds[3], '접수일': tds[5], '종국결과': tds[6],
#         '청구금액': tds[7], '확정일': tds[14].replace(".","-") if len(tds) > 14 else ""}
# =============================================================================


def parse_property(driver, soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    try:
        driver.find_element(By.CSS_SELECTOR, '#mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_tab_ssgoTab2_tabHTML').click()
        time.sleep(1)
        sub_soup = bs(driver.page_source, "html.parser")
        rows = sub_soup.select('tr.grid_body_row')
        last_prog = rows[-1].find_all('td') if rows else None
    except: last_prog = None
    
    return {
        '법원': row.get('법원', ''), '사건번호': tds[0], '관계자': row.get('관계자', ''),
        '사건명': tds[1],
        '채권자': tds[2], '채무자': tds[3], '접수일': tds[8].replace(".","-") if len(tds) > 8 else tds[5],
        '일자': last_prog[0].get_text(strip=True) if last_prog else "",
        '진행경과': last_prog[1].get_text(strip=True) if last_prog else ""
    }



# =========execl and load_data===================================
def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()


def load_data(file_path):
    if Path(file_path).exists():
        return pd.read_excel(file_path)
    return pd.DataFrame(columns=['법원', '사건번호', '관계자', '사업명'])







# ==================== Streamlit 메인 앱 ====================
def main():
    st.set_page_config(page_title="나의사건조회", layout="wide")
    st.subheader("⚖️ 나의 사건 현황 조회")    
    # 파일 경로 설정
    current_dir = Path(__file__).parent.absolute()
    fname = current_dir / 'data_sosong.xlsx'
    
    # 2. 세션 상태 초기화
    if 'df' not in st.session_state:
        st.session_state.df = load_data(fname)
    if 'is_running' not in st.session_state:
        st.session_state.is_running = False
    if 'stop_requested' not in st.session_state:
        st.session_state.stop_requested = False
    if 'final_results' not in st.session_state:
        st.session_state.final_results = None

    # 3. CSS 스타일 (탭 간격 및 폰트 개선)
    st.markdown("""
        <style>        
        div[data-testid="stTabs"] button [data-testid="stMarkdownContainer"] p {
            font-size: 18px !important; /* 탭 글자 크기 확장 */
            font-weight: bold;
        }
        /* 라디오 버튼 스타일 */
        div[class*="stRadio"] label p { 
            font-size: 18px !important; 
            font-weight: bold; 
            color: #1E90FF; 
        }
        /* 공통 버튼 스타일 */
        .stButton>button { 
            width: 100%; 
            font-weight: bold; 
            margin-top: 5px;
        }
        </style>
        """, unsafe_allow_html=True)

    # 4. 사이드바 메뉴
    with st.sidebar:
        selected = option_menu(
            "메인 메뉴", ["홈", "소송현황조회"], 
            icons=['house', 'search'], 
            default_index=1
        )

    # --- 페이지 분기 ---
    if selected == "홈":
        st.subheader("🏠 나의사건조회 시스템")
        st.write("대법원 나의사건조회 서비스를 자동화하여 다량의 사건 현황을 한 번에 파악할 수 있게 도와줍니다.")

    elif selected == "소송현황조회":
        # 메인 탭 구성
        tab1, tab2 = st.tabs(['🔍소송조회', '➕사건등록/관리'])
        with tab1:                               
            col1, col2, col3 = st.columns([4.5,1,4.5])
            
            with col1:
                st.markdown("**:red[사건정보입력(법원, 사건번호, 관계사)을 Tab으로 구분하여 붙여넣으세요]**")
                input_text = st.text_area(
                    "사건입력창",
                    height=200, 
                    placeholder="서울중앙지방법원\t2024가단12345\t홍길동",
                    label_visibility="collapsed"
                )
                
                mode_choice = st.radio("조회 방식 선택", ["소송조회(사건번호분류)", "일자별 진행상세 조회"], horizontal=True)
                
                c1, c2 = st.columns(2)
                with c1:
                    start_btn = st.button("조회 시작 🚀", disabled=st.session_state.is_running)
                with c2:
                    if st.button("🧹 결과 초기화"):
                        st.session_state.final_results = None
                        st.session_state.is_running = False
                        st.rerun()

# =============================================================================
#             with col3:
#                 with st.expander("사건DB"):
#                     st.info("💡 현재 등록된 사건 DB 리스트")
#                     # 등록된 데이터가 있을 경우만 필터 제공
#                     pj_list = st.session_state.df['사업명'].unique().tolist() if not st.session_state.df.empty else []
#                     pj_filter = st.selectbox("등록된 사업명으로 필터링", pj_list)
#                     
#                     st_df = st.session_state.df
#                     st_df = st_df[st_df['사업명'] == pj_filter]
#                     
#                     st.dataframe(st_df[['법원', '사건번호', '관계자']], use_container_width=True, height=250, hide_index=True)
#                     st.metric(label="건수", value=len(st_df))
# =============================================================================

        with tab2: # 사건등록관리
            # 1. 세션 상태 초기화
            if 'authenticated' not in st.session_state:
                st.session_state.authenticated = False        
            # 2. 인증되지 않은 경우: 로그인 화면 표시
            if not st.session_state.authenticated:
                st.subheader("🔒 보안구역")
                password = st.text_input("액세스 비밀번호를 입력하세요", type="password")                
                if st.button("접속하기"):
                    if password == "7840":
                        st.session_state.authenticated = True
                        st.rerun()  # 성공 시 재실행하여 아래 'else' 구간으로 진입
                    else:
                        st.error("비밀번호가 올바르지 않습니다.")
        
            # 3. 인증된 경우: 메인 사건 등록/현황 화면 표시
            else:
                # 상단에 로그아웃 버튼 배치
                if st.button("사건관리 로그아웃"): # 사이드바 혹은 상단에 배치
                    st.session_state.authenticated = False
                    st.rerun()
        
                # 세 개의 컬럼으로 분할 (단일등록, 대량등록, 현황보기)
                col_single, col_multi, col_view = st.columns([1, 1, 1.5])
        
                # --- 1. 단일 사건 등록 (기존 Form) ---
                with col_single:
                    st.subheader('📝 건별 등록')
                    with st.form(key='single_form', clear_on_submit=True):
                        court = st.text_input("법원")
                        number = st.text_input("사건번호")
                        rel_person = st.text_input("관계자")
                        pj_name = st.text_input("사업명")
                        if st.form_submit_button("사건 등록"):
                            if court and number and rel_person:
                                new_data = {'법원': court, '사건번호': number, '관계자': rel_person, '사업명': pj_name}
                                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_data])], ignore_index=True)
                                st.session_state.df.to_excel(fname, index=False)
                                st.success("등록 완료!")
                                st.rerun()
                            else:
                                st.warning("필수 항목을 입력하세요.")
        
                # --- 2. 대량 사건 등록 (Text Area) ---
                with col_multi:
                    st.subheader('📦 대량 등록')
                    st.caption("형식: 법원, 사건번호, 관계자, 사업명 (줄바꿈 구분)")
                    raw_input = st.text_area("데이터 붙여넣기", placeholder="서울중앙, 2024가단1, 홍길동, A사업", height=250)
                    
                    if st.button("일괄 등록 실행"):
                        if raw_input.strip():
                            lines = raw_input.strip().split('\n')
                            new_rows = []
                            for line in lines:
                                # 쉼표나 탭으로 구분된 데이터를 리스트로 변환
                                parts = [p.strip() for p in line.replace('\t', ',').split(',')]
                                if len(parts) >= 4:
                                    new_rows.append({'법원': parts[0], '사건번호': parts[1], '관계자': parts[2], '사업명': parts[3]})
                            
                            if new_rows:
                                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame(new_rows)], ignore_index=True)
                                st.session_state.df.to_excel(fname, index=False)
                                st.success(f"{len(new_rows)}건 등록 성공!")
                                st.rerun()
                            else:
                                st.error("형식이 맞지 않습니다.")

                # --- 3. 등록 사건 현황 ---
                with col_view:
                    st.subheader("📂 등록현황")
                    pj_list = st.session_state.df['사업명'].unique().tolist() if not st.session_state.df.empty else []
                    sel_pj = st.selectbox("사업명 필터", ["전체"] + pj_list)                    
                    # 전체 데이터 가져오기
                    full_df = st.session_state.df.copy()                    
                    # 1. 화면에 표시할 데이터 준비
                    if sel_pj != "전체":
                        display_df = full_df[full_df['사업명'] == sel_pj]
                    else:
                        display_df = full_df                
                    # 2. 데이터 에디터 (st_df = ... 형태의 대입문 삭제)
                    edit_df = st.data_editor(
                        display_df,
                        num_rows="dynamic",
                        use_container_width=True,
                        key="main_db_editor",
                        height=400)
                    
                    if st.button("💾 모든 변경사항 최종 저장"):
                        st.session_state.df = edit_df
                        st.session_state.df.to_excel(fname, index=False)
                        st.success("엑셀 파일이 성공적으로 업데이트되었습니다.")
                        st.rerun()
                    
        if start_btn and input_text:
            try:
                #lines = [line.split() for line in input_text.strip().split("\n") if line.strip()]
                lines = [re.split(r'\t+', line.strip()) for line in input_text.strip().split("\n") if line.strip()]
                df = pd.DataFrame(lines, columns=['법원', '사건번호', '관계자'])
                extracted = df['사건번호'].str.extract(r'^(\d{4})\s*([^\d\s]+)\s*(\d+)$')                
                df['연도'], df['구분'], df['번호'] = extracted[0], extracted[1], extracted[2]
                df = df.dropna(subset=['연도', '구분', '번호'])
            except:
                st.error("데이터 파싱 실패. 형식을 확인하세요.")
                return

            st.session_state.is_running = True
            st.session_state.stop_requested = False
            
            # [수정] "가압류가처분" 키 추가
            results_dict = {"소송": [], "지급명령": [], "재산명시": [], "조정": [], "가압류가처분": [], "진행상세": []}
            
            bot = CourtAutomation()
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, row in df.iterrows():
                if st.session_state.stop_requested: break
                
                if "소송조회(사건번호분류)" in mode_choice:
                    case_type = str(row['구분']).strip()
                    if case_type == '카명': mode = "재산명시"
                    elif case_type == '차전': mode = "지급명령"
                    elif case_type in ['머', '조정']: mode = "조정"
                    elif case_type in ['카단','카합']: mode = "가압류가처분"  # [수정] 모드 할당
                    else: mode = "소송"
                else:
                    mode = "진행상세"

                status_text.info(f"[{i+1}/{len(df)}] {row['사건번호']} 조회 중... ({mode})")
                bot.navigate_to_search(row)
                soup = bot.solve_captcha()
                
                if soup:
                    #if mode == "소송": data = parse_litigation(soup, row)
                    if mode in "소송": data = parse_litigation(soup, row)
                    elif mode == "가압류가처분": data = parse_preattach(soup, row)
                    elif mode == "진행상세": data = parse_detail(bot.driver, row)
                    elif mode == "지급명령": data = parse_payment_order(soup, row)
                    elif mode == "조정": data = parse_nego(soup, row)
                    elif mode == "재산명시": data = parse_property(bot.driver, soup, row)

                    if data:
                        if isinstance(data, list): results_dict[mode].extend(data)
                        else: results_dict[mode].append(data)
                
                progress_bar.progress((i + 1) / len(df))

            bot.quit()
            # 조회가 모두 끝났으므로 버튼을 다시 활성화합니다.
            st.session_state.is_running = False
            st.markdown("---")
            #dictionary.items() 함수는 모든 키(Key)와 값(Value)의 쌍을 튜플(Tuple) 형태로 묶어서 반환
            
            active_modes = [m for m, res in results_dict.items() if res]
            
            if active_modes:
                tabs = st.tabs(active_modes)
                for idx, mode_name in enumerate(active_modes):
                    with tabs[idx]:
                        res_df = pd.DataFrame(results_dict[mode_name])
                        cols = ['법원','사건번호','관계자'] + [col for col in res_df.columns if col not in ['법원','사건번호','관계자']]                        
                        res_df = res_df[cols]                        
                        st.dataframe(res_df, use_container_width=True, hide_index=True)
                        
                        excel_data = to_excel(res_df)
                        st.download_button(
                            label=f"📥 {mode_name} 결과 엑셀 다운로드",
                            data=excel_data,
                            file_name=f"{mode_name}_{datetime.now().strftime('%y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.ms-excel",
                            key=f"dl_{mode_name}"
                        )
            else:
                st.warning("조회된 결과가 없습니다.")

    elif selected == "홈":
        st.subheader("🏠 나의사건조회 ")
        st.write("대법원 나의사건조회 서비스를 자동화하여 다량의 사건 현황을 한 번에 파악할 수 있게 도와줍니다.")

if __name__ == "__main__":
    main()
