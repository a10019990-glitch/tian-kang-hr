import streamlit as st
import pandas as pd

# --- 設定區 ---
# 這是你試算表的 ID，我已經幫你從網址中提取出來了
SHEET_ID = "1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc"
# 這是分頁名稱，請確認 Google Sheet 下方標籤叫 salary_data
SHEET_NAME = "salary_data"

# 建立一個「萬用讀取網址」
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端薪資管理系統 (直連版)")
    
    # 1. 登入邏輯
    if 'auth' not in st.session_state:
        st.subheader("🔐 雲端登入")
        user = st.text_input("帳號 (例如: boss 或 mgr_04)")
        if st.button("確認進入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # 2. 讀取雲端資料 (使用最原始的 pd.read_csv)
    try:
        # 這是目前全世界讀取 Google Sheet 最穩定的方法
        all_df = pd.read_csv(CSV_URL)
        all_df = all_df.dropna(how='all', axis=0) # 刪除空行
    except Exception as e:
        st.error(f"❌ 還是讀不到資料！錯誤訊息：{e}")
        st.write(f"請檢查 Google Sheet 分頁名稱是否真的叫：{SHEET_NAME}")
        return

    # 3. 檢查欄位
    if '月份' not in all_df.columns:
        st.error("❌ 找不到『月份』欄位！")
        st.write(f"系統目前看到的標題是：{list(all_df.columns)}")
        st.info("請檢查 Excel 第一行有沒有『月份』這兩個字。")
        return

    # --- 成功進入後的畫面 ---
    role = st.session_state.auth
    shop = st.session_state.shop
    st.sidebar.success(f"目前權限：{shop}")
    
    target_month = st.sidebar.selectbox("選擇月份", ["2026-02", "2026-03", "2026-04"])

    # 過濾資料
    all_df['月份'] = all_df['月份'].astype(str)
    all_df['店別'] = all_df['店別'].astype(str)
    mask = (all_df['月份'] == target_month)
    if role == 3: mask = mask & (all_df['店別'] == shop)
    current_view = all_df[mask].copy()

    st.header(f"📅 {target_month} 薪資明細")
    if current_view.empty:
        st.warning(f"目前雲端找不到 {target_month} 的資料。")
    
    # 顯示表格
    st.data_editor(current_view, num_rows="dynamic")
    st.info("💡 提醒：若要修改資料，請直接在 Google Sheet 上改，改完後重新整理此網頁即可。")

if __name__ == "__main__":
    main()
