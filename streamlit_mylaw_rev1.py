
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
import os

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
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    return {
        '법원': row['법원'], '사건번호': tds[0].split('[')[0], '관계자': row['관계자'],
        '사건명': tds[1], '원고': tds[2], '피고': tds[3], '접수일': tds[5],
        '소송결과': tds[6], '확정일': tds[20] if len(tds) > 20 else ""
    }

def parse_preattach(soup, row):
    """가압류가처분(카단) 전용 파싱"""
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    
    # 카단 사건은 일반 사건과 테이블 구조가 다르므로 인덱스 체크 필수
    return {
        '법원': row['법원'], 
        '사건번호': tds[0].split('[')[0] if len(tds) > 0 else "",
        '관계자': row['관계자'],
        '사건명': tds[1] if len(tds) > 1 else "",
        '채권자': tds[2] if len(tds) > 2 else "",
        '채무자': tds[3] if len(tds) > 3 else "",
        '청구금액': tds[5] if len(tds) > 5 else "",
        '접수일': tds[8] if len(tds) > 8 else "",
        '종국결과': tds[9] if len(tds) > 9 else "",
        '결정문송달일': tds[19] if len(tds) > 19 else ""
    }

def parse_payment_order(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    return {'법원사건번호': row['법원'] + tds[0], '사건명': tds[1], '채권자': tds[2], '채무자': tds[3], '접수일': tds[5], '종국결과': tds[6]}

def parse_property(driver, soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    return {'사건번호': row['법원'] + tds[0], '채권자': tds[2], '채무자': tds[3], '접수일': tds[8] if len(tds) > 8 else tds[5]}

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

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

# ==================== Streamlit 메인 앱 ====================
def main():
    st.set_page_config(page_title="나의사건조회", layout="wide")
    
    # 세션 초기화
    if 'final_results' not in st.session_state: st.session_state.final_results = None
    if 'is_running' not in st.session_state: st.session_state.is_running = False
    if 'stop_requested' not in st.session_state: st.session_state.stop_requested = False

    st.markdown("""<style>
                div[class*="stRadio"] label p { font-size: 20px !important; font-weight: bold; color: #1E90FF; }
                .stButton>button { width: 100%; font-weight: bold; }
                </style>""", unsafe_allow_html=True)

    with st.sidebar:
        selected = option_menu("메인 메뉴", ["홈", "소송현황조회"], icons=['house', 'search'], default_index=1)

    if selected == "소송현황조회":
        st.title("⚖️ 나의 사건 현황 조회")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            input_text = st.text_area("사건 정보 입력", height=200, placeholder="서울중앙지방법원\t2024가단12345\t홍길동")
            mode_choice = st.radio("조회 방식 선택", ["자동 분류 (사건번호 기준)", "일자별 진행상세 조회"], horizontal=True)

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1: start_btn = st.button("조회 시작 🚀", disabled=st.session_state.is_running)
        with c2: 
            if st.button("🛑 조회 중단"):
                st.session_state.stop_requested = True
                st.warning("중단 요청됨...")
        with c3:
            if st.button("🧹 결과 초기화"):
                st.session_state.final_results = None
                st.rerun()

        if start_btn and input_text:
            try:
                lines = [line.split("\t") for line in input_text.strip().split("\n") if line.strip()]
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
            temp_results = {"소송": [], "지급명령": [], "재산명시": [], "조정": [], "가압류가처분": [], "진행상세": []}
            
            bot = CourtAutomation()
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, row in df.iterrows():
                if st.session_state.stop_requested: break
                
                if "자동 분류" in mode_choice:
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
                    if mode == "소송": data = parse_litigation(soup, row)
                    elif mode == "가압류가처분": data = parse_preattach(soup, row)
                    elif mode == "진행상세": data = parse_detail(bot.driver, row)
                    elif mode == "지급명령": data = parse_payment_order(soup, row)
                    elif mode == "재산명시": data = parse_property(bot.driver, soup, row)

                    if data:
                        if isinstance(data, list): temp_results[mode].extend(data)
                        else: temp_results[mode].append(data)
                
                progress_bar.progress((i + 1) / len(df))

            bot.quit()
            st.session_state.final_results = temp_results
            st.session_state.is_running = False
            st.rerun()

        # 결과 출력 (세션 유지)
        if st.session_state.final_results:
            st.markdown("---")
            active_data = {k: v for k, v in st.session_state.final_results.items() if v}
            if active_data:
                tabs = st.tabs(list(active_data.keys()))
                for idx, (m_name, m_list) in enumerate(active_data.items()):
                    with tabs[idx]:
                        res_df = pd.DataFrame(m_list)
                        st.dataframe(res_df, use_container_width=True, hide_index=True)
                        st.download_button(f"📥 {m_name} 엑셀 다운로드", to_excel(res_df), f"{m_name}.xlsx", key=f"dl_{m_name}")

if __name__ == "__main__":

    main()
