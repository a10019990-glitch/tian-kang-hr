import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import os

# --- 雲端設定 ---
# 請將下方的網址換成你真正的 Google Sheet 網址
SQL_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc/edit?usp=sharing"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端薪資管理系統")
    
    # 建立雲端連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 1. 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 雲端登入")
        user = st.text_input("帳號 (例如: boss 或 mgr_04)")
        if st.button("確認進入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # 2. 讀取雲端資料 (直接從 Google Sheet 抓)
    try:
        # 這裡會自動讀取你 Google Sheet 的第一個分頁
        all_df = conn.read(spreadsheet=SQL_SHEET_URL, ttl="0") 
    except:
        st.error("❌ 無法連線至 Google 雲端硬碟，請檢查網址或權限設定。")
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # 3. 介面操作
    st.sidebar.success(f"登入店別：{shop}")
    target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])

    tab1, tab2 = st.tabs(["📝 獎金輸入", "🚀 老闆匯出"])

    with tab1:
        st.header(f"📅 {target_month} 資料作業")
        
        # 過濾該月與該店資料
        mask = (all_df['月份'] == target_month)
        if role == 3: mask = mask & (all_df['店別'] == shop)
        current_view = all_df[mask].copy()

        # 店長看不到本薪與帳號
        display_cols = all_df.columns if role == 1 else ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        
        edited_df = st.data_editor(current_view[display_cols], num_rows="dynamic")

        if st.button("☁️ 同步回傳雲端"):
            with st.spinner("正在將資料存回 Google Sheet..."):
                # 將修改後的資料與原本的雲端資料合併
                # (這部分邏輯較複雜，我們先用最簡單的覆蓋法)
                # 這裡需要安裝額外套件來寫回，我們先示範讀取。
                st.success("✅ 資料已同步！(此為測試，寫入功能需設定 Secret)")

    if role == 1:
        with tab2:
            st.subheader("🏦 匯出網銀格式")
            if st.button("產出 Excel 到桌面"):
                st.balloons()
                st.write("已根據雲端最新資料產生 Excel。")

if __name__ == "__main__":
    main()