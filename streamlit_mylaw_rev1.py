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

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.alert import Alert
from selenium.common.exceptions import NoAlertPresentException

# ==================== 설정 ====================
import os
# 환경 변수에 따라 경로 설정 (윈도우면 로컬 경로, 아니면 리눅스 기본 경로)
if os.name == 'nt':  # Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
else:  # Linux (Streamlit Cloud)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

#TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
#pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# ==================== CourtAutomation 클래스 ====================
class CourtAutomation:
    def __init__(self):
        self.driver = self._create_driver()
        self.wait = WebDriverWait(self.driver, 10)

    def _create_driver(self):
        options = Options()
        options.add_argument("--headless")  # 서버 환경을 위해 화면 없이 실행
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        return webdriver.Chrome(options=options)

    def solve_captcha(self):
        captcha_img_xpath = '//*[@id="mf_ssgoTopMainTab_contents_content1_body_img_captcha"]'
        reload_btn_id = 'mf_ssgoTopMainTab_contents_content1_body_btn_reloadCaptcha'
        answer_box_id = "mf_ssgoTopMainTab_contents_content1_body_ibx_answer"
        search_btn_id = "mf_ssgoTopMainTab_contents_content1_body_btn_srchCs"

        for attempt in range(10):
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
            except:
                continue
        return None

    def navigate_to_search(self, row):
        self.driver.get("https://www.scourt.go.kr/portal/information/events/search/search.jsp")
        self.wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "#contants > iframe")))
        
        Select(self.wait.until(EC.presence_of_element_located((By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_cortCd")))).select_by_visible_text(row['법원'])
        time.sleep(0.5)
        
        Select(self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_csYr")).select_by_visible_text(str(row['연도']))
        Select(self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_sbx_csDvsCd")).select_by_visible_text(row['구분'])
        
        serial = self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_ibx_csSerial")
        serial.clear()
        serial.send_keys(str(row['번호']))
        
        name = self.driver.find_element(By.ID, "mf_ssgoTopMainTab_contents_content1_body_ibx_btprNm")
        name.clear()
        name.send_keys(row['관계자'])

    def quit(self):
        self.driver.quit()

# ==================== 파싱 함수들 ====================

def parse_litigation(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    
    tbl_date = soup.find('table', id=lambda x: x and 'rcntDxdyLst' in x)
    date_info = [""] * 5
    if tbl_date and tbl_date.find('td'):
        g = list(zip(*[iter(tbl_date.find_all('td'))] * 5))
        date_info = [','.join(td.text.strip() for td in [group[idx] for group in g]) for idx in range(5)]

    return {
        '법원': row['법원'], '사건번호': tds[0].split('[')[0], '관계자': row['관계자'],
        '사건명': tds[1].replace("[전자]",""), '원고': tds[2], '피고': tds[3], '접수일': tds[5].replace(".","-"),
        '소송결과': tds[6], '원고소가': tds[7], '확정일': tds[20].replace(".","-") if len(tds) > 20 else "",
        '기일일자': date_info[0], '진행경과': date_info[4]
    }

def parse_nego(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    
    # 기일 정보 처리
    tbl_date = soup.find('table', id=lambda x: x and 'rcntDxdyLst' in x)
    date_info = [""] * 5
    if tbl_date and tbl_date.find('td'):
        g = list(zip(*[iter(tbl_date.find_all('td'))] * 5))
        date_info = [','.join(td.text.strip() for td in [group[idx] for group in g]) for idx in range(5)]
    return {
        '법원': row['법원'], '사건번호': tds[0].split('[')[0], '관계자': row['관계자'],
        '사건명': tds[1].replace("[전자]",""), '원고': tds[2], '피고': tds[3], '접수일': tds[5].replace(".","-"),
        '소송결과': tds[6], '원고소가': tds[7], '수리구분': tds[9], '확정일': tds[16],
        '일자': date_info[0], '진행경과': date_info[4]
    }
    

def parse_payment_order(soup, row):
    tbl = soup.find('table', id=lambda x: x and 'ssgoCsDetailTab' in x)
    if not tbl: return None
    tds = [td.get_text(strip=True) for td in tbl.find_all('td')]
    return {
        '법원사건번호': row['법원'] + tds[0], '사건명': tds[1].replace("[전자]",""),
        '채권자': tds[2], '채무자': tds[3], '접수일': tds[5], '종국결과': tds[6],
        '청구금액': tds[7], '확정일': tds[14].replace(".","-") if len(tds) > 14 else ""
    }

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
        '사건번호': row['법원'] + tds[0].split('[')[0], '사건명': tds[1],
        '채권자': tds[2], '채무자': tds[3], '접수일': tds[8].replace(".","-") if len(tds) > 8 else tds[5],
        '마지막진행일자': last_prog[0].get_text(strip=True) if last_prog else "",
        '진행내용': last_prog[1].get_text(strip=True) if last_prog else ""
    }

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
                    rows_data.append({
                        '법원': row['법원'], '사건번호': f"{row['연도']}{row['구분']}{row['번호']}",
                        '일자': cells[0].get_text(strip=True), '진행내용': cells[1].get_text(strip=True)
                    })
        return rows_data
    except: return []

# ==================== 데이터 유틸리티 ====================
def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

# ==================== Streamlit 메인 앱 ====================
def main():
    st.set_page_config(page_title="법원 사건조회", layout="wide")
    st.markdown("""<style>
                /* 라디오 버튼 전체 옵션 텍스트 크기 */
                div[data-testid="stMarkdownContainer"] p {
                    font-size: 18px !important;
                }
                /* 라디오 버튼의 개별 항목(label) 텍스트 크기 */
                div[class*="stRadio"] label p {
                    font-size: 20px !important;
                    font-weight: bold;
                }
                </style>
                """, unsafe_allow_html=True)

    with st.sidebar:
        selected = option_menu(
            "나의사건현황", ["홈", "소송현황조회"],
            icons=['house', 'search'],
            menu_icon="cast", default_index=1,
        )

    if selected == "소송현황조회":
        st.title("⚖️ 소송 현황 자동 조회")
        st.info("법원 / 사건번호 / 관계자 정보를 복사하여 입력창에 붙여넣으세요.")

        col1, col2 = st.columns([1, 1])
        with col1:
            input_text = st.text_area("사건 정보 입력 (탭 구분)", height=250, placeholder="서울중앙지방법원\t2024가단12345\t홍길동")          
            
        mode_choice = st.radio("조회 방식 선택", ["자동 분류 (사건번호 기준)", "일자별 진행상세 조회"],horizontal=True)

        if st.button("조회 시작 🚀"):
            if not input_text.strip():
                st.error("데이터를 입력해 주세요.")
                return

            # 데이터프레임 파싱
            try:
                lines = [line.split("\t") for line in input_text.strip().split("\n") if line.strip()]
                df = pd.DataFrame(lines, columns=['법원', '사건번호', '관계자'])
                extracted = df['사건번호'].str.extract(r'^(\d{4})\s*([^\d\s]+)\s*(\d+)$')
                #extracted = df['사건번호'].str.extract(r'^(\d{4})([^\d\s]+)(\d+)$') #streamlit은 clipboard사용안됨.
                df['연도'], df['구분'], df['번호'] = extracted[0], extracted[1], extracted[2]
                df = df.dropna()
            except:
                st.error("데이터 형식이 잘못되었습니다. [법원(Tab)사건번호(Tab)관계자] 형식을 확인하세요.")
                return

            # 결과 저장용 딕셔너리 (칼럼 불일치 해결)
            results_dict = {"소송": [], "지급명령": [], "재산명시": [], "조정": [], "진행상세": [], "가압류가처분": []}
            
            bot = CourtAutomation()
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, row in df.iterrows():
                try:
                    # 모드 결정
                    if mode_choice == "자동 분류 (사건번호 기준)":
                        case_type = row['구분']
                        if case_type == '카명': mode = "재산명시"
                        elif case_type == '차전': mode = "지급명령"
                        elif case_type == '머': mode = "조정"
                        else: mode = "소송"
                    else:
                        mode = "진행상세"

                    status_text.text(f"처리 중 ({i+1}/{len(df)}): {row['사건번호']} -> {mode}")
                    bot.navigate_to_search(row)
                    soup = bot.solve_captcha()
                    
                    if mode == "소송": data = parse_litigation(soup, row)
                    elif mode == "진행상세": data = parse_detail(bot.driver, row)
                    elif mode == "조정": data = parse_nego(soup, row)
                    elif mode == "지급명령": data = parse_payment_order(soup, row)
                    elif mode == "재산명시": data = parse_property(bot.driver, soup, row)

                    if data:
                        if isinstance(data, list): results_dict[mode].extend(data)
                        else: results_dict[mode].append(data)
                except Exception as e:
                    st.warning(f"{row['사건번호']} 조회 중 오류 발생: {e}")
                
                progress_bar.progress((i + 1) / len(df))

            bot.quit()
            status_text.success("조회 업무가 완료되었습니다.")

            # 결과 출력 영역
            st.markdown("---")
            active_modes = [m for m, res in results_dict.items() if res]
            
            if active_modes:
                tabs = st.tabs(active_modes)
                for idx, mode_name in enumerate(active_modes):
                    with tabs[idx]:
                        res_df = pd.DataFrame(results_dict[mode_name])
                        st.dataframe(res_df, use_container_width=True)
                        
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
        st.subheader("🏠 법원 사건조회 자동화 도구")
        st.write("이 도구는 대법원 나의사건조회 서비스를 자동화하여 다량의 사건 현황을 한 번에 파악할 수 있게 도와줍니다.")

if __name__ == "__main__":
    main()
