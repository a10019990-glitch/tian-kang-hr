import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- 設定工作表名稱 ---
# 請再次確認 Google Sheet 下方的分頁名稱已經改成英文：salary_data
TARGET_WORKSHEET = "salary_data"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端薪資管理系統")
    
    # 初始化雲端連線 (它會自動去 Secrets 找網址)
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 1. 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 雲端登入")
        user = st.text_input("帳號 (例如: boss 或 mgr_04)")
        if st.button("確認進入"):
            if user == "boss": 
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): 
                st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else:
                st.error("帳號不正確")
            st.rerun()
        return

    # 2. 讀取雲端資料
    try:
        # 直接讀取，不帶冗長的 URL 參數，減少 400 報錯機會
        all_df = conn.read(worksheet=TARGET_WORKSHEET, ttl="0")
        all_df = all_df.dropna(how='all') 
    except Exception as e:
        st.error(f"❌ 連線失敗！原因：{e}")
        st.info(f"💡 請檢查：1.雲端 Secrets 是否已儲存網址 2.分頁名稱是否為 {TARGET_WORKSHEET}")
        return

    # 3. 欄位檢查
    if '月份' not in all_df.columns:
        st.error(f"❌ 找不到『月份』欄位！")
        st.write(f"目前讀到的標題有：{list(all_df.columns)}")
        return

    # 顯示主畫面
    role = st.session_state.auth
    shop = st.session_state.shop
    st.sidebar.success(f"目前權限：{shop}")
    
    target_month = st.sidebar.selectbox("選擇月份", ["2026-02", "2026-03", "2026-04"])

    tab1, tab2 = st.tabs(["📝 獎金輸入作業", "🚀 報表匯出"])

    with tab1:
        st.header(f"📅 {target_month} 資料錄入")
        
        # 轉換格式避免比對失敗
        all_df['月份'] = all_df['月份'].astype(str)
        all_df['店別'] = all_df['店別'].astype(str)
        
        mask = (all_df['月份'] == target_month)
        if role == 3: mask = mask & (all_df['店別'] == shop)
        current_view = all_df[mask].copy()

        if current_view.empty:
            st.warning(f"目前找不到 {target_month} 的名單。")
        
        # 權限遮蔽
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = all_df.columns if role == 1 else [c for c in mgr_cols if c in all_df.columns]
        
        st.data_editor(current_view[display_cols], num_rows="dynamic", key="main_editor")
        st.info("💡 雲端版請直接在 Google Sheet 修改資料，網頁重新整理即可同步。")

if __name__ == "__main__":
    main()
