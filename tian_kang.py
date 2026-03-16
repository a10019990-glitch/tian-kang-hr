import streamlit as st
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取資料 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 網銀發薪專用系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("登入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # 讀取資料
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")

    # 校正欄位
    col_map = {c: "月份" for c in df_pay.columns if "月份" in c}
    col_map.update({c: "店別" for c in df_pay.columns if "店別" in c})
    col_map.update({c: "姓名" for c in df_pay.columns if "姓名" in c})
    df_pay = df_pay.rename(columns=col_map)

    if '月份' not in df_pay.columns:
        st.error("❌ 無法讀取月份資訊，請檢查 Google Sheet 第一行標題。")
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與匯出", "👤 員工基本資料", "🏥 勞健保紀錄"])

    with tab1:
        target_month = st.sidebar.selectbox("選擇月份", sorted(df_pay['月份'].unique().tolist(), reverse=True))
        
        # 篩選資料
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        mask = (df_pay['月份'] == target_month)
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        st.subheader(f"📍 {target_month} 核對清單")
        st.data_editor(current_pay, num_rows="dynamic", key="main_editor")

        # --- 老闆匯出區：精準對齊銀行格式 ---
        if role == 1:
            st.divider()
            st.subheader("🏦 匯出網銀格式 (自動計算總額與補齊資料)")
            pay_date = st.text_input("付款日期 (YYYYMMDD)", datetime.now().strftime("%Y%m%d"))
            
            if st.button("🚀 下載銀行發薪 CSV 檔"):
                if not df_emp.empty:
                    # 合併資料 (根據姓名抓取身分證、帳號、本薪)
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    
                    # 計算總金額
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus_cols:
                        if c in final_df.columns:
                            final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                        else:
                            final_df[c] = 0
                    
                    final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                    final_df['實領薪資'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                    # 建立銀行要求的 9 個欄位
                    bank_output = pd.DataFrame({
                        "付款日期": pay_date,
                        "轉帳項目": "901",  # 固定值
                        "企業編號": "5917",  # 固定值 (根據您的表單範例)
                        "員工姓名": final_df["姓名"],
                        "身分證字號": final_df["身分證"],
                        "收款帳號": final_df["收款帳號"],
                        "實領薪資": final_df["實領薪資"],
                        "附言": "轉帳存入",      # 固定值
                        "付款性質": "轉帳存入"     # 固定值 (通常 02 代表薪資)
                    })
                    
                    # 檢查資料完整性
                    missing = bank_output[bank_output['收款帳號'].isna()]
                    if not missing.empty:
                        st.warning(f"⚠️ 注意：員工 {list(missing['員工姓名'])} 缺少帳號或身分證，請至 emp_info 補齊。")

                    # 轉為 CSV 下載 (使用 utf-8-sig 確保中文在 Excel 不亂碼)
                    csv = bank_output.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 點我下載銀行 CSV 檔",
                        data=csv,
                        file_name=f"TianKang_Bank_{target_month}_{pay_date}.csv",
                        mime="text/csv"
                    )
                else:
                    st.error("❌ 找不到 emp_info，無法產出完整銀行檔。")

    with tab2: st.dataframe(df_emp)
    with tab3: st.dataframe(load_cloud_data("ins_info"))

if __name__ == "__main__":
    main()
