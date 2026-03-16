import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
# 請確認 Google Sheet 分頁名稱為 salary_data 和 emp_info
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def main():
    st.title("🚀 天康連鎖藥局 - 雲端自動同步系統")

    # 建立雲端連線 (需搭配 Service Account)
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_04)")
        if st.button("登入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # 讀取資料
    df_pay = conn.read(worksheet=PAY_SHEET, ttl="0")
    df_emp = conn.read(worksheet=EMP_SHEET, ttl="0")

    tab1, tab2 = st.tabs(["💰 薪資作業與自動存檔", "👤 員工基本資料"])

    with tab1:
        st.sidebar.header("⚙️ 管理功能")
        
        # --- 功能：自動新增月份 (老闆專屬) ---
        if role == 1:
            with st.sidebar.expander("➕ 自動開啟新月份"):
                new_month = st.text_input("輸入新月份 (如 2026-04)", "2026-04")
                if st.button("一鍵建立並寫入雲端"):
                    new_rows = pd.DataFrame({
                        "月份": [new_month] * len(df_emp),
                        "店別": df_emp["店別"],
                        "姓名": df_emp["姓名"],
                        "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0,
                        "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                    })
                    # 直接寫入 Google Sheet
                    updated_df = pd.concat([df_pay, new_rows], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=updated_df)
                    st.success(f"✅ {new_month} 名單已自動寫入雲端！")
                    st.rerun()

        # 薪資核對與修改
        months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
        target_month = st.sidebar.selectbox("核對月份", months)
        
        current_pay = df_pay[df_pay['月份'] == target_month].copy()
        if role == 3: current_pay = current_pay[current_pay['店別'] == shop]

        st.subheader(f"📍 {target_month} 資料編輯")
        edited_df = st.data_editor(current_pay, num_rows="dynamic", key="editor")

        # --- 核心：自動更新按鈕 ---
        if st.button("💾 將修改內容同步至 Google Sheet"):
            with st.spinner("同步中..."):
                # 把編輯後的資料塞回總表
                others = df_pay[~((df_pay['月份'] == target_month) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                final_to_save = pd.concat([others, edited_df], ignore_index=True)
                
                # 執行寫入動作
                conn.update(worksheet=PAY_SHEET, data=final_to_save)
                st.success("✅ 雲端資料已自動更新成功！")

if __name__ == "__main__":
    main()
