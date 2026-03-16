import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import re

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 強大格式修正工具
def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    # 清理標題
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    
    # 標題對應
    mapping = {}
    for c in df.columns:
        if "店別" in c or "店號" in c: mapping[c] = "店別"
        if "姓名" in c: mapping[c] = "姓名"
        if "月份" in c: mapping[c] = "月份"
    df = df.rename(columns=mapping)

    # 【核心修正】將店別統一格式化
    if "店別" in df.columns:
        def format_shop_id(val):
            # 抓出數字部分
            nums = re.findall(r'\d+', str(val))
            if nums:
                return nums[0].zfill(2) # 統一變成 01, 04, 11 這種格式
            return str(val).strip()
        df["店別"] = df["店別"].apply(format_shop_id)
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 雲端管理系統")

    conn = st.connection("gsheets", type=GSheetsConnection)

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_04)")
        if st.button("登入"):
            if user == "boss":
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"):
                # 登入帳號也強制轉成兩位數 (如 mgr_4 變 04)
                shop_id = re.findall(r'\d+', user)
                st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "ERROR"
            st.rerun()
        return

    # 讀取資料
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))

    role = st.session_state.auth
    shop = st.session_state.shop

    st.sidebar.info(f"📍 登入分店：{shop}")

    # --- 老闆專屬診斷區 ---
    if role == 1:
        with st.expander("🔍 [大助專用] 資料庫格式診斷"):
            col1, col2 = st.columns(2)
            col1.write("📊 薪資表中的現存店別：")
            col1.code(df_pay['店別'].unique().tolist() if '店別' in df_pay.columns else "找不到店別欄位")
            col2.write("👤 員工表中的現存店別：")
            col2.code(df_emp['店別'].unique().tolist() if '店別' in df_emp.columns else "找不到店別欄位")

    tab1, tab2 = st.tabs(["💰 薪資獎金作業", "👤 員工基本資料"])

    with tab1:
        if not df_pay.empty and '月份' in df_pay.columns:
            # 月份篩選
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("核對月份", months)
            
            # 關鍵過濾邏輯
            mask = (df_pay['月份'].astype(str) == str(target_month))
            if role == 3:
                mask = mask & (df_pay['店別'] == shop)
            
            display_df = df_pay[mask].copy()

            if display_df.empty:
                st.warning(f"⚠️ 找不到 {target_month} 月份店號 『{shop}』 的資料。")
                st.info("請確認 Google Sheet 中是否有該月份且店號正確的列。")
            else:
                st.subheader(f"📅 {target_month} 獎金核對表")
                # 隱藏敏感欄位給店長
                mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
                cols = display_df.columns if role == 1 else [c for c in mgr_cols if c
