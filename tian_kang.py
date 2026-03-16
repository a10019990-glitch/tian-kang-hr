import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 (已更新為你的新表單 ID) ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取資料並自動校正欄位 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        # 移除標題所有空格與換行，防止抓不到欄位
        df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端管理系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 權限登入")
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else: st.error("帳號不正確"); return
            st.rerun()
        return

    # --- 讀取雲端三大分頁 ---
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")
    df_ins = load_cloud_data("ins_info")

    # 【自動校正欄位名】：模糊
