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
    st.title("☁️ 天康連鎖藥局 - 雲端自動化管理系統")

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("登入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop
    
    # 讀取雲端資料
    df_pay = load_cloud_data("salary_data")
    df_emp = load_cloud_data("emp_info")
    
    # 校正標題
    df_pay = df_pay.rename(columns={c: "月份" for c in df_pay.columns if "月份" in c})
    df_pay = df_pay.rename(columns={c: "店別" for c in df_pay.columns if "店別" in c})
    df_pay = df_pay.rename(columns={c: "姓名" for c in df_pay.columns if "姓名" in c})

    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與初始化", "👤 員工基本資料", "🏥 勞健保紀錄"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        st.sidebar.header("⚙️ 系統功能")
        
        # 功能 A：新增月份 (老闆專屬)
        if role == 1:
            with st.sidebar.expander("➕ 建立新月份名單"):
                new_month = st.text_input("輸入新月份 (如 2026-03)", "2026-03")
                if st.button("生成新月份模板"):
                    if not df_emp.empty:
                        # 根據基本資料庫生成名單
                        new_template = pd.DataFrame({
                            "月份": new_month,
                            "店別": df_emp.get("店別", "請填寫"),
                            "姓名": df_emp["姓名"],
                            "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0, 
                            "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                        })
                        st.write(f"📋 請複製下方表格並貼入 Google Sheet 的 salary_data 分頁：")
                        st.dataframe(new_template)
                        st.download_button("📥 下載此月模板 CSV", new_template.to_csv(index=False).encode('utf-8-sig'), f"template_{new_month}.csv")
                    else:
                        st.error("請先在 emp_info 填入員工名單")

        # 選擇現有月份
        months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
        target_month = st.sidebar.selectbox("切換核對月份", months)
        
        # 篩選當月資料
        df_pay['月份'] = df_pay['月份'].astype(str)
        df_pay['店別'] = df_pay['店別'].astype(str)
        current_pay = df_pay[df_pay['月份'] == target_month].copy()
        if role == 3: current_pay = current_pay[current_pay['店別'] == shop]

        # 功能 B：同步檢查 (檢查是否有員工在基本資料庫但不在本月名單)
        if not df_emp.empty and target_month != "無資料":
            emp_names = set(df_emp["姓名"])
            pay_names = set(current_pay["姓名"])
            missing_names = list(emp_names - pay_names)
            
            if missing_names:
                st.warning(f"⚠️ 偵測到新員工：{missing_names} 尚未加入 {target_month} 的薪資表！")
                if st.button("生成補齊名單"):
                    missing_df = df_emp[df_emp['姓名'].isin(missing_names)][['姓名']].copy()
                    missing_df['月份'] = target_month
                    missing_df['店別'] = "請填寫"
                    st.write("👇 請複製這幾行貼到 Google Sheet 最後面：")
                    st.dataframe(missing_df)

        st.subheader(f"📍 {target_month} 核對清單")
        mgr_show = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_show if c in current_pay.columns]
        st.data_editor(current_pay[display_cols], num_rows="dynamic", key="main_editor")

        # 匯出功能 (自動帶入最新個資)
        if role == 1:
            st.divider()
            if st.button("🚀 產出銀行發薪檔 (連動最新個資)"):
                # Merge 最新個資，確保就算 emp_info 剛改過，這裡抓到的也是最新的
                final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                
                bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                for c in bonus_cols: final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                final_df['總額'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                bank_csv = pd.DataFrame({
                    "付款日期": datetime.now().strftime("%Y%m%d"),
                    "轉帳項目": "901", "企業編號": "75440263",
                    "姓名": final_df["姓名"], "身分證": final_df["身分證"],
                    "帳號": final_df["收款帳號"], "金額": final_df["總額"], "附言": "薪資", "性質": "02"
                })
                st.download_button("📥 下載銀行 CSV", bank_csv.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")

    # --- Tab 2: 基本資料 (老闆可直接看) ---
    with tab2:
        st.header("👤 員工資料庫 (emp_info)")
        st.dataframe(df_emp)

if __name__ == "__main__":
    main()
