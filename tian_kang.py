import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- 雲端連線設定 ---
# 1. 請確認你的 Google Sheet 網址（建議使用「知道連結的任何人」權限）
SQL_SHEET_URL = "https://docs.google.com/spreadsheets/d/1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc/edit?usp=sharing"
# 2. 這裡已經改為英文，請確認 Google Sheet 下方分頁也改為 salary_data
TARGET_WORKSHEET = "salary_data"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端薪資管理系統")
    
    # 初始化雲端連線
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
                st.error("帳號錯誤")
            st.rerun()
        return

    # 2. 讀取雲端資料 (增加錯誤處理)
    try:
        # 這裡指定讀取英文名稱的分頁
        all_df = conn.read(spreadsheet=SQL_SHEET_URL, worksheet=TARGET_WORKSHEET, ttl="0")
        all_df = all_df.dropna(how='all') 
    except Exception as e:
        st.error(f"❌ 讀取失敗！原因可能是：{e}")
        st.info(f"💡 請檢查 Google Sheet 下方的分頁名稱是否已改為: {TARGET_WORKSHEET}")
        return

    # 3. 欄位安全性檢查
    if '月份' not in all_df.columns:
        st.error(f"❌ 找不到『月份』欄位！")
        st.write(f"目前讀到的欄位有：{list(all_df.columns)}")
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    st.sidebar.success(f"目前權限：{shop}")
    
    # 選擇月份
    target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])

    tab1, tab2 = st.tabs(["📝 獎金輸入作業", "🚀 報表匯出"])

    with tab1:
        st.header(f"📅 {target_month} 資料錄入")
        
        # 過濾數據：確保『月份』和『店別』都是字串格式進行比對
        all_df['月份'] = all_df['月份'].astype(str)
        all_df['店別'] = all_df['店別'].astype(str)
        
        mask = (all_df['月份'] == target_month)
        if role == 3: mask = mask & (all_df['店別'] == shop)
        current_view = all_df[mask].copy()

        if current_view.empty:
            st.warning(f"目前在雲端找不到 {target_month} 的員工資料。")
        
        # 店長看不到機密欄位
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = all_df.columns if role == 1 else [c for c in mgr_cols if c in all_df.columns]
        
        # 像 Excel 一樣編輯
        st.data_editor(current_view[display_cols], num_rows="dynamic", key="main_editor")
        st.info("💡 提醒：目前版本為『雲端讀取』，若要儲存修改，請直接在 Google Sheet 上作業，網頁重新整理後會同步。")

if __name__ == "__main__":
    main()
