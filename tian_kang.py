import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 ---
# 請確保這個 ID 是你「新表」的 ID
SHEET_ID = "1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取資料並自動校正欄位 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        # 移除標題所有空格與換行
        df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端管理系統 (修復版)")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # --- 讀取資料 ---
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")

    # 【自動校正欄位名】：防止因為空格或字體導致的 KeyError
    col_mapping = {}
    for actual_col in df_pay.columns:
        if "月份" in actual_col: col_mapping[actual_col] = "月份"
        if "店別" in actual_col: col_mapping[actual_col] = "店別"
        if "姓名" in actual_col: col_mapping[actual_col] = "姓名"
    
    df_pay = df_pay.rename(columns=col_mapping)

    # 檢查是否還有缺
    if '月份' not in df_pay.columns or '店別' not in df_pay.columns:
        st.error("❌ 還是找不到『月份』或『店別』欄位！")
        st.write("📊 電腦目前看到的欄位名有：", list(df_pay.columns))
        st.info("💡 請檢查 Google Sheet 的第一行是否有正確的標題。")
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與匯出", "👤 員工基本資料", "🏥 勞健保紀錄"])

    with tab1:
        target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])
        
        # 篩選
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        mask = (df_pay['月份'].str.contains(target_month))
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        st.subheader(f"📍 {target_month} 明細核對")
        
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_cols if c in current_pay.columns]
        
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        if role == 1:
            st.divider()
            st.subheader("🏦 匯出網銀發薪檔")
            pay_date = st.text_input("付款日期 (YYYYMMDD)", datetime.now().strftime("%Y%m%d"))
            
            if st.button("🚀 生成發薪清冊 (含帳號/ID)"):
                if not df_emp.empty:
                    # 合併資料
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    
                    # 計算總和 (將各項獎金加起來)
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus_cols: final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                    final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                    
                    final_df['實領金額'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                    bank_output = pd.DataFrame({
                        "付款日期": pay_date,
                        "姓名": final_df["姓名"],
                        "身分證號": final_df["身分證"],
                        "銀行帳號": final_df["收款帳號"],
                        "金額": final_df["實領金額"]
                    })
                    
                    csv = bank_output.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 下載網銀 CSV", data=csv, file_name=f"bank_{target_month}.csv")
                else:
                    st.error("缺少 emp_info 資料")

    with tab2: st.dataframe(load_cloud_data("emp_info"))
    with tab3: st.dataframe(load_cloud_data("ins_info"))

if __name__ == "__main__":
    main()
