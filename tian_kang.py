import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 (請確保 Google Sheet 分頁名稱正確) ---
# 分頁名稱務必改為英文：salary_data, emp_info, ins_info
SHEET_ID = "1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取並清洗資料 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip() # 自動刪除標題前後的空格，解決「找不到欄位」問題
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端全功能管理系統")

    # --- 3. 登入邏輯 ---
    if 'auth' not in st.session_state:
        st.subheader("🔐 員工入口")
        user = st.text_input("帳號 (boss 或 mgr_04/11/12/13/15/77)")
        if st.button("登入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else: st.error("帳號無效"); return
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    # 建立三個分頁
    tab1, tab2, tab3 = st.tabs(["💰 每月薪資核對", "👤 員工基本資料", "🏥 勞健保查詢"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        st.sidebar.header("📅 時間與篩選")
        target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])
        
        df_pay = load_cloud_data("salary_data")
        df_emp = load_cloud_data("emp_info")

        if df_pay.empty:
            st.error("❌ 無法讀取『salary_data』分頁，請檢查 Google Sheet。")
            return

        # 過濾該月與店別
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        mask = (df_pay['月份'] == target_month)
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        # 核心：自動帶入資料 (勾稽 emp_info)
        if st.button("🔍 勾稽基本資料 (自動補齊帳號/ID/本薪)"):
            if not df_emp.empty:
                # 根據姓名合併
                current_pay = current_pay.drop(columns=['身分證字號', '收款帳號', '本薪'], errors='ignore')
                current_pay = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '本薪']], left_on='姓名', right_on='姓名', how='left')
                st.success("✅ 已從『員工基本資料』同步最新帳號與本薪！")
            else:
                st.error("找不到 emp_info 資料。")

        # 權限遮蔽
        mgr_view_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_view_cols if c in current_pay.columns]
        
        st.subheader(f"📍 {target_month} 薪資明細 ({'全體' if role==1 else f'店別 {shop}'})")
        edited_df = st.data_editor(current_pay[display_cols], num_rows="dynamic", key="pay_edit")

        # 匯出功能 (雲端版改為下載按鈕)
        if role == 1:
            st.divider()
            st.subheader("🏦 老闆專屬：產出網銀發薪檔")
            if st.button("🚀 準備匯出檔案"):
                # 這裡會產出一個下載按鈕
                csv = edited_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 點我下載 2月網銀格式.csv", data=csv, file_name=f"tian_kang_bank_{target_month}.csv", mime="text/csv")

    # --- Tab 2: 員工基本資料 (僅老闆可看可改) ---
    with tab2:
        if role == 1:
            st.header("👤 員工主資料庫")
            st.info("💡 這裡的修改請直接在 Google Sheet 的『emp_info』分頁進行，網頁重新整理後會更新。")
            st.dataframe(df_emp)
        else:
            st.warning("🔒 店長無權限查看員工私密資料。")

    # --- Tab 3: 勞健保查詢 ---
    with tab3:
        st.header("🏥 勞健保與加退保紀錄")
        df_ins = load_cloud_data("ins_info")
        if not df_ins.empty:
            if role == 3:
                st.dataframe(df_ins[df_ins['店別'].astype(str) == shop])
            else:
                st.dataframe(df_ins)
        else:
            st.write("目前無資料。")

if __name__ == "__main__":
    main()
