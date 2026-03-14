import streamlit as st
import pandas as pd

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"

def get_sheet_url(sheet_name):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

st.set_page_config(page_title="天康藥局全功能管理系統", layout="wide")

# --- 2. 核心功能：讀取資料並自動診斷 ---
def load_cloud_data(name):
    try:
        url = get_sheet_url(name)
        df = pd.read_csv(url)
        # 這裡很關鍵：自動刪除所有欄位名稱的空格
        df.columns = [str(c).strip() for c in df.columns]
        return df.dropna(how='all', axis=0)
    except:
        return pd.DataFrame()

def main():
    st.title("☁️ 天康連鎖藥局 - 雲端管理系統 (含自動診斷)")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_04/11/12/13/15/77)")
        if st.button("登入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else: st.error("帳號無效"); return
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    tab1, tab2, tab3 = st.tabs(["💰 薪資獎金核對", "👤 員工基本資料", "🏥 勞健保紀錄"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        df_pay = load_cloud_data("salary_data")
        
        # 檢查關鍵欄位是否存在
        required_cols = ['月份', '店別', '姓名']
        missing_cols = [c for c in required_cols if c not in df_pay.columns]
        
        if missing_cols:
            st.error(f"❌ 在 'salary_data' 分頁找不到這些欄位: {missing_cols}")
            st.write("📊 目前電腦看到的欄位名稱有：", list(df_pay.columns))
            st.info("💡 請去 Google Sheet 修改第一行，確保名字完全正確（沒有多餘的字或符號）。")
            return

        # 這裡開始執行功能
        st.sidebar.header("📅 篩選設定")
        target_month = st.sidebar.selectbox("處理月份", ["2026-02", "2026-03", "2026-04"])

        # 格式轉換，確保比對成功
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        
        mask = (df_pay['月份'] == target_month)
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        # 勾稽功能 (連動基本資料)
        if st.button("🔍 自動補齊員工 ID 與 帳號"):
            df_emp = load_cloud_data("emp_info")
            if not df_emp.empty:
                # 移除重複欄位避免報錯
                current_pay = current_pay.drop(columns=['身分證', '收款帳號'], errors='ignore')
                # 根據姓名把 emp_info 的資料塞進來
                current_pay = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                st.success("✅ 已根據基本資料庫補齊 ID 與 帳號！")
            else:
                st.error("找不到 emp_info 資料庫。")

        # 店長遮蔽邏輯
        mgr_show = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_show if c in current_pay.columns]
        
        st.subheader(f"📍 {target_month} 薪資明細")
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        if role == 1:
            st.divider()
            st.subheader("🏦 匯出銀行發薪檔")
            pay_date = st.text_input("付款日期 (YYYYMMDD)", "20260305")
            if st.button("🚀 準備下載 Excel"):
                # 整理成銀行格式
                bank_df = pd.DataFrame({
                    "付款日期": pay_date,
                    "轉帳項目": "901",
                    "員工姓名": current_pay["姓名"],
                    "員工ID": current_pay.get("身分證", ""),
                    "收款帳號": current_pay.get("收款帳號", ""),
                    "交易金額": current_pay.get("實領金額", 0)
                })
                csv = bank_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button("📥 點我下載網銀格式.csv", data=csv, file_name=f"bank_{target_month}.csv")

    # --- Tab 2 & 3 (簡化顯示) ---
    with tab2:
        df_emp = load_cloud_data("emp_info")
        st.write("👤 員工資料庫內容：")
        st.dataframe(df_emp)

    with tab3:
        df_ins = load_cloud_data("ins_info")
        st.write("🏥 勞健保資料內容：")
        st.dataframe(df_ins)

if __name__ == "__main__":
    main()
