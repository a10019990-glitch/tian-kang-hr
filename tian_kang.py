import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 自動修正欄位名稱的工具
def clean_df_columns(df):
    if df.empty: return df
    # 移除空格與換行
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    # 模糊比對修正
    col_map = {}
    for c in df.columns:
        if "月份" in c: col_map[c] = "月份"
        if "店別" in c: col_map[c] = "店別"
        if "姓名" in c: col_map[c] = "姓名"
    return df.rename(columns=col_map)

def main():
    st.title("🚀 天康連鎖藥局 - 雲端管理系統")

    # 建立雲端連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_04)")
        if st.button("登入"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # --- 讀取並自動校正資料 ---
    df_pay = clean_df_columns(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = clean_df_columns(conn.read(worksheet=EMP_SHEET, ttl="0"))

    role = st.session_state.auth
    shop = st.session_state.shop

    tab1, tab2 = st.tabs(["💰 薪資核對與存檔", "👤 員工基本資料"])

    with tab1:
        st.sidebar.header("⚙️ 管理功能")
        
        # --- 自動新增月份 (老闆專屬) ---
        if role == 1:
            with st.sidebar.expander("➕ 自動開啟新月份"):
                new_month = st.text_input("輸入新月份 (如 2026-04)", "2026-04")
                if st.button("一鍵建立並寫入雲端"):
                    if "店別" not in df_emp.columns:
                        st.error("❌ 無法建立！員工資料表 (emp_info) 裡面找不到『店別』欄位。")
                        st.write("目前 emp_info 的欄位有：", list(df_emp.columns))
                    else:
                        new_rows = pd.DataFrame({
                            "月份": [new_month] * len(df_emp),
                            "店別": df_emp["店別"],
                            "姓名": df_emp["姓名"],
                            "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0,
                            "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                        })
                        updated_df = pd.concat([df_pay, new_rows], ignore_index=True)
                        conn.update(worksheet=PAY_SHEET, data=updated_df)
                        st.success(f"✅ {new_month} 名單已自動寫入雲端！")
                        st.rerun()

        # 薪資顯示與修改
        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("核對月份", months)
            
            # 確保篩選欄位存在
            df_pay['月份'] = df_pay['月份'].astype(str)
            df_pay['店別'] = df_pay['店別'].astype(str)
            
            current_pay = df_pay[df_pay['月份'] == target_month].copy()
            if role == 3: current_pay = current_pay[current_pay['店別'] == shop]

            st.subheader(f"📍 {target_month} 資料編輯")
            edited_df = st.data_editor(current_pay, num_rows="dynamic", key="editor")

            if st.button("💾 將修改內容同步至 Google Sheet"):
                with st.spinner("同步中..."):
                    # 過濾掉當前編輯的部分，再把新的補回去
                    mask = (df_pay['月份'] == target_month)
                    if role == 3: mask = mask & (df_pay['店別'] == shop)
                    others = df_pay[~mask]
                    final_to_save = pd.concat([others, edited_df], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=final_to_save)
                    st.success("✅ 雲端資料已自動更新成功！")
        else:
            st.warning("目前 salary_data 是空的，請先使用左側功能建立月份。")

    with tab2:
        st.subheader("👤 員工資料庫 (emp_info)")
        st.dataframe(df_emp)

if __name__ == "__main__":
    main()
