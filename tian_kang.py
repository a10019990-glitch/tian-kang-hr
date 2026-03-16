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
        df.columns = [str(c).strip() for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 全自動薪資與勞健保同步系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("登入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    # 讀取雲端三大分頁
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")
    df_ins = load_cloud_data("ins_info")
    
    # 校正標題
    df_pay = df_pay.rename(columns={c: "月份" for c in df_pay.columns if "月份" in c})
    df_pay = df_pay.rename(columns={c: "店別" for c in df_pay.columns if "店別" in c})
    df_pay = df_pay.rename(columns={c: "姓名" for c in df_pay.columns if "姓名" in c})

    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與發薪", "👤 員工基本資料", "🏥 勞健保明細"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        # 月份選擇
        months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
        target_month = st.sidebar.selectbox("切換月份", months)
        
        # 篩選當月資料
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        current_pay = df_pay[df_pay['月份'] == target_month].copy()
        if role == 3: current_pay = current_pay[current_pay['店別'] == shop]

        st.subheader(f"📍 {target_month} 核對清單")
        mgr_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_cols if c in current_pay.columns]
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        # --- 老闆匯出區：包含勞健保同步扣款 ---
        if role == 1:
            st.divider()
            st.subheader("🏦 匯出銀行發薪檔 (自動扣除勞健保)")
            
            if st.button("🚀 生成最終發薪清冊"):
                if not df_emp.empty and not df_ins.empty:
                    # 1. 合併基本資料 (抓本薪、帳號)
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    
                    # 2. 合併勞健保資料 (抓扣款金額)
                    # 確保 ins_info 裡面的欄位叫做「勞健保個人負擔」
                    final_df = final_df.merge(df_ins[['姓名', '勞健保個人負擔']], on='姓名', how='left')
                    
                    # 3. 計算總金額
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus_cols: 
                        final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                    
                    final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                    final_df['勞健保扣款'] = pd.to_numeric(final_df['勞健保個人負擔'], errors='coerce').fillna(0)
                    
                    # 計算公式：本薪 + 獎金 - 勞健保
                    final_df['實領總額'] = (final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)) - final_df['勞健保扣款']

                    # 4. 銀行格式
                    bank_csv = pd.DataFrame({
                        "付款日期": datetime.now().strftime("%Y%m%d"),
                        "轉帳項目": "901",
                        "企業編號": "75440263",
                        "員工姓名": final_df["姓名"],
                        "身分證字號": final_df["身分證"],
                        "收款帳號": final_df["收款帳號"],
                        "交易金額": final_df["實領總額"],
                        "附言": "薪資",
                        "付款性質": "02"
                    })
                    
                    # 顯示預覽並下載
                    st.write("📊 即將匯出的金額預覽 (已扣除勞健保)：")
                    st.dataframe(bank_output := bank_csv[["員工姓名", "交易金額"]])
                    
                    st.download_button(
                        label="📥 下載銀行發薪 CSV",
                        data=bank_csv.to_csv(index=False).encode('utf-8-sig'),
                        file_name=f"TianKang_Final_{target_month}.csv",
                        mime="text/csv"
                    )
                else:
                    st.error("❌ 缺少 emp_info 或 ins_info 資料，無法同步扣款。")

    # --- Tab 2 & 3: 唯讀資料 ---
    with tab2:
        st.header("👤 員工資料庫 (emp_info)")
        st.dataframe(df_emp)
    with tab3:
        st.header("🏥 勞健保資料庫 (ins_info)")
        st.dataframe(df_ins)

if __name__ == "__main__":
    main()
