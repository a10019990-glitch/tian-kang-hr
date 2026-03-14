import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import os

# --- 雲端設定 ---
# 1. 貼上你的 Google Sheet 網址
SQL_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc/edit?usp=sharing"
# 2. 確認工作表名稱 (如果你分頁名字不是「明細」，請改掉下面這兩個字)
TARGET_WORKSHEET = "明細"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端薪資管理系統")
    
    # 建立雲端連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 雲端登入")
        user = st.text_input("帳號 (例如: boss 或 mgr_04)")
        if st.button("確認進入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # 讀取雲端資料
    try:
        # 特別指定讀取名為「明細」的分頁
        all_df = conn.read(spreadsheet=SQL_SHEET_URL, worksheet=TARGET_WORKSHEET, ttl="0")
        # 清洗資料：刪除全空的行，避免干擾
        all_df = all_df.dropna(how='all') 
    except Exception as e:
        st.error(f"❌ 無法讀取 Google Sheet：{e}")
        st.info("請確認：1.網址正確 2.分頁名稱叫做『明細』 3.權限已開為『知道連結的任何人皆可編輯』")
        return

    # 檢查是否真的有「月份」這一欄
    if '月份' not in all_df.columns:
        st.error(f"❌ 找不到『月份』欄位！目前讀到的欄位有：{list(all_df.columns)}")
        st.write("請檢查 Google Sheet 第一行是否有『月份』這兩個字。")
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    st.sidebar.success(f"登入店別：{shop}")
    
    target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])

    tab1, tab2 = st.tabs(["📝 獎金輸入", "🚀 老闆匯出"])

    with tab1:
        st.header(f"📅 {target_month} 資料作業")
        
        # 過濾該月與該店資料
        mask = (all_df['月份'].astype(str) == target_month)
        if role == 3: mask = mask & (all_df['店別'].astype(str) == shop)
        current_view = all_df[mask].copy()

        if current_view.empty:
            st.warning(f"目前雲端表單中找不到 {target_month} 的資料。")
        
        # 店長隱私過濾
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = all_df.columns if role == 1 else [c for c in mgr_cols if c in all_df.columns]
        
        st.data_editor(current_view[display_cols], num_rows="dynamic")
        st.info("💡 雲端直接寫入功能目前受 Google API 限制，建議在 Google Sheet 修改後重新整理網頁。")

if __name__ == "__main__":
    main()
