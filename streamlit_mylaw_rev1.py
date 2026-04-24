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
        self.driver.set_page_load_timeout(30) 
        self.wait = WebDriverWait(self.driver, 15)

    def _create_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                  get: () => undefined
                })
            """
        })
        return driver

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
        try:
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
        except Exception as e:
            st.error(f"페이지 접속 중 오류 발생: {e}")
            return False

    def quit(self):
        self.driver.quit()

# ==================== 파싱 함수들 ====================
def parse_litigation(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    res = {th.get_text(strip=True): td.get_text(strip=True) 
           for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}
    
    tbl_date = soup.find('table', id=lambda x: x and 'wfRcntDxdyLst_grd_rcntDxdyLst_body_table' in x)
    date_info = ["기일미지정"] + [""] * 4
    if tbl_date:
        all_tds = tbl_date.find_all('td')
        if all_tds:
            groups = [all_tds[i:i+5] for i in range(0, len(all_tds), 5)]
            parsed = [','.join(g[idx].get_text(strip=True) for g in groups if len(g) > idx) for idx in range(5)]
            if parsed[0].strip(): date_info = parsed
            
    res.update({
        '법원': row.get('법원', ''),
        '관계자': row.get('관계자', ''),
        '기일일자': date_info[0],
        '진행경과': date_info[4],
        '사건번호': str(res.get('사건번호', '')).split('[')[0].strip(),
        '사건명': res.get('사건명', '').replace('[전자]', "").strip()
    })    
    try:
        tbl2 = soup.find('table', id=lambda x: x and 'rcntSbmsnDocmtLst_body_table' in x)
        res['최근제출서류'] = tbl2.find_all('td')[-1].text if tbl2 else ""
    except: res['최근제출서류'] =""
    
    dates = res['기일일자']
    has_date = dates and dates != "기일미지정"
    res['기일차수'] = len(set(dates.split(','))) if has_date else 0
    res['최종일자'] = dates.split(',')[-1].strip() if has_date else "기일미지정"        
    return res

def parse_payment_order(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tbl_map = {th.get_text(strip=True): td.get_text(strip=True) 
                for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}         
    tbl_map['사건번호'] = tbl_map['사건번호'].split('[')[0]
    tbl_map['사건명'] = tbl_map['사건명'].replace('[전자]',"")
    tbl_map.update({'관계자': row.get('관계자', '')})            
    try:
        tbl1 = soup.find('table', id=lambda x: x and 'reltCsCtt_body_table' in x)
        if tbl1:
            tds = tbl1.find_all('td')
            if len(tds) > 0: tbl_map['법원2'] = tds[0].get_text(strip=True)
            if len(tds) > 1: tbl_map['관련사건'] = tds[1].get_text(strip=True)
            else: tbl_map['관련사건'] = ""
    except:
        tbl_map['법원2'] = ""
        tbl_map['관련사건'] = ""    
    return tbl_map

def parse_nego(soup, row):    
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None    
    res = {th.get_text(strip=True): td.get_text(strip=True) 
           for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}
    tbl_date = soup.find('table', id=lambda x: x and 'rcntDxdyLst' in x)
    date_info = ["기일미지정"] + [""] * 4
    if tbl_date:
        all_tds = tbl_date.find_all('td')
        if all_tds:
            groups = [all_tds[i:i+5] for i in range(0, len(all_tds), 5)]
            parsed = [','.join(g[idx].get_text(strip=True) for g in groups if len(g) > idx) for idx in range(5)]
            if parsed[0].strip(): date_info = parsed
    res.update({
        '법원': row.get('법원', ''), '관계자': row.get('관계자', ''),
        '기일일자': date_info[0], '진행경과': date_info[4],
        '사건번호': str(res.get('사건번호', '')).split('[')[0].strip(),
        '사건명': res.get('사건명', '').replace('[전자]', "").strip()
    })    
    return res

def parse_detail(driver, row):    
    try:
        driver.find_element(By.CSS_SELECTOR, '#mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_tab_ssgoTab2_tabHTML').click()
        time.sleep(1)         
        soup = bs(driver.page_source, "html.parser")            
        tbody = soup.find('tbody', id='mf_ssgoTopMainTab_contents_content1_body_wfSsgoDetail_ssgoCsDetailTab_contents_ssgoTab2_body_grd_csProgLst_body_tbody')        
        res = []
        if tbody:
            for tr in tbody.find_all('tr', class_='grid_body_row'):
                cells = tr.find_all('td')
                if len(cells) >= 2:
                    res.append({'법원': row['법원'], '사건번호': row['사건번호'], '관계자': row['관계자'], '일자': cells[0].get_text(strip=True), '내용': cells[1].get_text(strip=True)})
        return res
    except: return []

def parse_preattach(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tbl_map = {th.get_text(strip=True): td.get_text(strip=True) 
                for th, td in zip(tbl.find_all('th'), tbl.find_all('td'))}          
    tbl_map['사건번호'] = tbl_map['사건번호'].split('[')[0]
    tbl_map['사건명'] = tbl_map['사건명'].replace('[전자]',"")
    tbl_map.update({'법원': row.get('법원', ''), '관계자': row.get('관계자', '')})    
    return tbl_map

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
        '사건명': tds[1], '채권자': tds[2], '채무자': tds[3], 
        '접수일': tds[8].replace(".","-") if len(tds) > 8 else tds[5],
        '일자': last_prog[0].get_text(strip=True) if last_prog else "",
        '진행경과': last_prog[1].get_text(strip=True) if last_prog else ""
    }

# ==================== 유틸리티 ====================
def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False)
    return output.getvalue()

def load_data(file_path):
    if Path(file_path).exists(): return pd.read_excel(file_path)
    return pd.DataFrame(columns=['법원', '사건번호', '관계자', '사업명'])

# ==================== Streamlit 메인 앱 ====================
def main():
    st.set_page_config(page_title="나의사건조회", layout="wide")
    st.subheader("⚖️ 나의 사건 현황 조회")    
    current_dir = Path(__file__).parent.absolute()
    fname = current_dir / 'data_sosong.xlsx'
    
    # --- 1. 세션 상태 초기화 ---
    if 'df' not in st.session_state:
        st.session_state.df = load_data(fname)
    if 'is_running' not in st.session_state:
        st.session_state.is_running = False
    if 'stop_requested' not in st.session_state:
        st.session_state.stop_requested = False
    # [중요] 조회 결과를 저장할 세션 딕셔너리
    if 'all_results' not in st.session_state:
        st.session_state.all_results = {}

    st.markdown("""
        <style>       
        div[data-testid="stTabs"] button [data-testid="stMarkdownContainer"] p { font-size: 18px !important; font-weight: bold; }
        div[class*="stRadio"] label p { font-size: 18px !important; font-weight: bold; color: #1E90FF; }
        .stButton>button { width: 100%; font-weight: bold; margin-top: 5px; }
        </style>
        """, unsafe_allow_html=True)

    with st.sidebar:
        selected = option_menu("메인 메뉴", ["홈", "소송현황조회"], icons=['house', 'search'], default_index=1)

    if selected == "홈":
        st.subheader("🏠 나의사건조회 시스템")
        st.write("대법원 나의사건조회 서비스를 자동화하여 다량의 사건 현황을 한 번에 파악할 수 있게 도와줍니다.")

    elif selected == "소송현황조회":
        tab1, tab2 = st.tabs(['🔍소송조회', '➕사건등록/관리'])
        
        with tab1:                                
            col1, _, col3 = st.columns([4.5,1,4.5])
            with col1:
                st.markdown("**:red[사건정보입력(법원, 사건번호, 관계사)을 콤마(,)로 구분하여 붙여넣으세요]**")
                input_text = st.text_area("사건입력창", height=150, placeholder="서울중앙지방법원, 2024가단12345, 홍길동", label_visibility="collapsed")
                mode_choice = st.radio("조회 방식 선택", ["소송조회(사건번호분류)", "일자별 진행상세 조회"], horizontal=True)
                
                c1, c2 = st.columns(2)
                with c1:
                    start_btn = st.button("조회 시작 🚀", disabled=st.session_state.is_running)
                with c2:
                    if st.button("🧹 결과 초기화"):
                        st.session_state.all_results = {}
                        st.session_state.is_running = False
                        st.rerun()
            
            if start_btn and input_text:
                try:                    
                    lines = [re.split(r'\s*,\s*', line.strip()) for line in input_text.strip().split("\n") if line.strip()]
                    df_input = pd.DataFrame(lines, columns=['법원', '사건번호', '관계자'])
                    extracted = df_input['사건번호'].str.extract(r'^(\d{4})\s*([^\d\s]+)\s*(\d+)$')                
                    df_input['연도'], df_input['구분'], df_input['번호'] = extracted[0], extracted[1], extracted[2]
                    df_input = df_input.dropna(subset=['연도', '구분', '번호'])
                except:
                    st.error("데이터 파싱 실패. 형식을 확인하세요.")
                    return

                st.session_state.is_running = True
                st.session_state.stop_requested = False
                # 조회 시작 시 세션 결과 초기화
                st.session_state.all_results = {"소송": [], "지급명령": [], "재산명시": [], "조정": [], "가압류가처분": [], "진행상세": []}
                
                bot = CourtAutomation()
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, row in df_input.iterrows():
                    if st.session_state.stop_requested: break
                    
                    case_type = str(row['구분']).strip()
                    if "소송조회" in mode_choice:
                        if case_type == '카명': mode = "재산명시"
                        elif case_type == '차전': mode = "지급명령"
                        elif case_type in ['머', '조정']: mode = "조정"
                        elif case_type in ['카단','카합']: mode = "가압류가처분"
                        else: mode = "소송"
                    else: mode = "진행상세"

                    status_text.info(f"[{i+1}/{len(df_input)}] {row['사건번호']} 조회 중... ({mode})")
                    bot.navigate_to_search(row)
                    soup = bot.solve_captcha()
                    
                    if soup:
                        if mode == "소송": data = parse_litigation(soup, row)
                        elif mode == "가압류가처분": data = parse_preattach(soup, row)
                        elif mode == "진행상세": data = parse_detail(bot.driver, row)
                        elif mode == "지급명령": data = parse_payment_order(soup, row)
                        elif mode == "조정": data = parse_nego(soup, row)
                        elif mode == "재산명시": data = parse_property(bot.driver, soup, row)

                        if data:
                            if isinstance(data, list): st.session_state.all_results[mode].extend(data)
                            else: st.session_state.all_results[mode].append(data)
                    
                    progress_bar.progress((i + 1) / len(df_input))

                bot.quit()
                st.session_state.is_running = False
                st.rerun() # 화면 갱신하여 결과 탭 표시

            # --- 결과 출력 영역 (세션 상태 데이터 기반) ---
            if st.session_state.all_results:
                active_modes = [m for m, res in st.session_state.all_results.items() if res]
                if active_modes:
                    st.markdown("---")
                    res_tabs = st.tabs(active_modes)
                    for idx, mode_name in enumerate(active_modes):
                        with res_tabs[idx]:
                            res_df = pd.DataFrame(st.session_state.all_results[mode_name])
                            # 컬럼 순서 조정
                            cols = ['법원','사건번호','관계자'] + [col for col in res_df.columns if col not in ['법원','사건번호','관계자']]                        
                            res_df = res_df[cols]                        
                            st.dataframe(res_df, use_container_width=True, hide_index=True)
                            
                            excel_data = to_excel(res_df)
                            st.download_button(
                                label=f"📥 {mode_name} 결과 엑셀 다운로드",
                                data=excel_data,
                                file_name=f"{mode_name}_{datetime.now().strftime('%y%m%d_%H%M')}.xlsx",
                                mime="application/vnd.ms-excel",
                                key=f"dl_{mode_name}" # 고유 키
                            )
                elif not st.session_state.is_running:
                    st.info("조회된 결과가 없습니다.")

        with tab2: # 사건등록관리 (인증 로직 포함)
            if 'authenticated' not in st.session_state: st.session_state.authenticated = False        
            if not st.session_state.authenticated:
                st.subheader("🔒 보안구역")
                password = st.text_input("액세스 비밀번호를 입력하세요", type="password")                
                if st.button("접속하기"):
                    if password == "000000":
                        st.session_state.authenticated = True
                        st.rerun()
                    else: st.error("비밀번호가 올바르지 않습니다.")
            else:
                if st.button("사건관리 로그아웃"):
                    st.session_state.authenticated = False
                    st.rerun()
        
                col_single, col_multi, col_view = st.columns([1, 1, 1.5])
                with col_single:
                    st.subheader('📝 건별 등록')
                    with st.form(key='single_form', clear_on_submit=True):
                        court = st.text_input("법원")
                        number = st.text_input("사건번호")
                        rel_person = st.text_input("관계자")
                        pj_name = st.text_input("사업명")
                        if st.form_submit_button("사건 등록"):
                            if court and number and rel_person:
                                new_row = {'법원': court, '사건번호': number, '관계자': rel_person, '사업명': pj_name}
                                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([new_row])], ignore_index=True)
                                st.session_state.df.to_excel(fname, index=False)
                                st.success("등록 완료!")
                                st.rerun()
                
                with col_multi:
                    st.subheader('📦 대량 등록')
                    raw_input = st.text_area("데이터 붙여넣기(법원, 번호, 관계자, 사업명)", height=200)
                    if st.button("일괄 등록 실행"):
                        if raw_input.strip():
                            lines = raw_input.strip().split('\n')
                            new_rows = []
                            for line in lines:
                                parts = [p.strip() for p in line.replace('\t', ',').split(',')]
                                if len(parts) >= 4:
                                    new_rows.append({'법원': parts[0], '사건번호': parts[1], '관계자': parts[2], '사업명': parts[3]})
                            if new_rows:
                                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame(new_rows)], ignore_index=True)
                                st.session_state.df.to_excel(fname, index=False)
                                st.success(f"{len(new_rows)}건 등록 완료!")
                                st.rerun()

                with col_view:
                    st.subheader("📂 등록현황")
                    pj_list = st.session_state.df['사업명'].unique().tolist() if not st.session_state.df.empty else []
                    sel_pj = st.selectbox("사업명 필터", ["전체"] + pj_list)
                    display_df = st.session_state.df if sel_pj == "전체" else st.session_state.df[st.session_state.df['사업명'] == sel_pj]
                    
                    edit_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, key="db_editor", height=300)
                    if st.button("💾 변경사항 최종 저장"):
                        st.session_state.df = edit_df
                        st.session_state.df.to_excel(fname, index=False)
                        st.success("저장 완료!")

if __name__ == "__main__":
    main()
