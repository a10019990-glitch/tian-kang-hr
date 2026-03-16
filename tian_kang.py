import streamlit as st
import pandas as pd

# --- 1. 雲端設定 ---
SHEET_ID = "1DPOtSzamSDEbSZLkhpGNuTsBk-mqbsYHY6cGnHQDDOc"

def get_sheet_url(sheet_name):
    # 使用轉為 CSV 的方式讀取 Google Sheet
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心功能：讀取資料 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        df.columns = [str(c).strip() for c in df.columns] # 移除欄位前後空白
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 自動化發薪系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與匯出", "👤 員工基本資料", "🏥 勞健保紀錄"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        df_pay = load_cloud_data("salary_data")
        df_emp = load_cloud_data("emp_info")
        
        target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])

        if df_pay.empty or '姓名' not in df_pay.columns:
            st.error("❌ 無法讀取發薪表，請確認分頁名稱為 salary_data 且包含『姓名』欄位。")
            return

        # 篩選資料
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        mask = (df_pay['月份'] == target_month)
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        st.subheader(f"📍 {target_month} 獎金與薪資核對")
        
        # 店長能看到的欄位
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_cols if c in current_pay.columns]
        
        # 顯示編輯表
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        # --- 老闆專區：銀行檔匯出 ---
        if role == 1:
            st.divider()
            st.subheader("🏦 匯出網銀專用格式")
            pay_date = st.text_input("預計付款日期 (如: 20260305)", datetime.now().strftime("%Y%m%d"))
            
            if st.button("🚀 生成發薪清冊 (自動帶入帳號/ID)"):
                if not df_emp.empty:
                    # 【核心動作】在背景自動將 emp_info 的帳號跟 ID 抓進來
                    # 確保 emp_info 的欄位名稱叫「身分證」和「收款帳號」
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    
                    # 計算總金額 = 基本薪資合計 + 獎金項目總和
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for col in bonus_cols:
                        final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0)
                    
                    final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                    final_df['應領總額'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                    # 整理成銀行需要的乾淨格式
                    bank_output = pd.DataFrame({
                        "付款日期": pay_date,
                        "員工姓名": final_df["姓名"],
                        "身分證字號": final_df["身分證"],
                        "銀行帳號": final_df["收款帳號"],
                        "轉帳金額": final_df["應領總額"],
                        "備註": "薪資"
                    })
                    
                    # 檢查是否有空白資料
                    empty_check = bank_output[bank_output['銀行帳號'].isna()]
                    if not empty_check.empty:
                        st.warning(f"⚠️ 警告：員工 {list(empty_check['員工姓名'])} 缺少帳號資訊，請檢查『emp_info』分頁。")

                    # 產出下載按鈕
                    csv_data = bank_output.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 下載網銀發薪 CSV 檔",
                        data=csv_data,
                        file_name=f"TianKang_Salary_{target_month}.csv",
                        mime="text/csv"
                    )
                    st.success("✅ 銀行檔已備妥，請點擊上方按鈕下載。")
                else:
                    st.error("❌ 找不到基本資料庫 (emp_info)，無法抓取帳號。")

    # --- Tab 2 & 3: 唯讀顯示 ---
    with tab2:
        st.dataframe(load_cloud_data("emp_info"))
    with tab3:
        st.dataframe(load_cloud_data("ins_info"))

if __name__ == "__main__":
    from datetime import datetime
    main()
