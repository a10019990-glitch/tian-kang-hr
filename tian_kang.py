import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

def clean_df(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    col_map = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    col_map.update({c: "姓名" for c in df.columns if "姓名" in c})
    col_map.update({c: "月份" for c in df.columns if "月份" in c})
    return df.rename(columns=col_map)

def main():
    st.title("🚀 天康連鎖藥局 - 權限分級管理系統")

    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 登入邏輯 (帳號分級核心) ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (請輸入 boss 或店號 mgr_xx)")
        if st.button("登入系統"):
            if user == "boss": 
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): 
                st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            else: 
                st.error("帳號無效"); return
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # 讀取雲端資料
    df_pay = clean_df(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = clean_df(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = clean_df(conn.read(worksheet=INS_SHEET, ttl="0"))

    # 側邊欄顯示狀態
    st.sidebar.success(f"目前身分：{'總公司 (老闆)' if role==1 else f'店長 (分店:{shop})'}")
    if st.sidebar.button("登出"):
        del st.session_state['auth']
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["💰 薪資獎金作業", "👤 員工基本資料", "🏥 勞健保查詢"])

    # --- Tab 1: 薪資作業 (分權核心) ---
    with tab1:
        # A. 管理功能：只有老闆可以開啟新月份
        if role == 1:
            with st.sidebar.expander("➕ [管理] 自動開啟新月份"):
                new_month = st.text_input("輸入新月份 (如 2026-04)", "2026-04")
                if st.button("確認寫入雲端"):
                    new_rows = pd.DataFrame({
                        "月份": [new_month] * len(df_emp),
                        "店別": df_emp.get("店別", "請填寫"),
                        "姓名": df_emp["姓名"],
                        "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0,
                        "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                    })
                    updated_pay = pd.concat([df_pay, new_rows], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=updated_pay)
                    st.success(f"✅ {new_month} 已建立。"); st.rerun()

        # B. 篩選與顯示
        months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
        target_month = st.sidebar.selectbox("核對月份", months)
        
        # 店長只能看到自己店，老闆看全體
        mask = (df_pay['月份'] == target_month)
        if role == 3: mask = mask & (df_pay['店別'] == shop)
        current_pay = df_pay[mask].copy()

        # 欄位遮蔽：店長看不到個資與實領總額，只能看獎金
        mgr_view = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
        display_cols = current_pay.columns if role == 1 else [c for c in mgr_view if c in current_pay.columns]
        
        st.subheader(f"📍 {target_month} 薪資核對 - {shop if role==3 else '全體'}")
        edited_df = st.data_editor(current_pay[display_cols], num_rows="dynamic", key="pay_editor")

        # C. 存檔與匯出按鈕
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 同步修改至雲端"):
                # 將修改的部分合併回總表
                others = df_pay[~((df_pay['月份'] == target_month) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                final_save = pd.concat([others, edited_df], ignore_index=True)
                conn.update(worksheet=PAY_SHEET, data=final_save)
                st.success("✅ 存檔成功！")

        with c2:
            if role == 1: # 只有老闆可以匯出銀行檔
                if st.button("🚀 匯出網銀發薪 CSV"):
                    final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                    bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus_cols: final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                    final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                    final_df['實領'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                    bank_output = pd.DataFrame({
                        "付款日期": datetime.now().strftime("%Y%m%d"),
                        "轉帳項目": "901", "企業編號": "75440263",
                        "員工姓名": final_df["姓名"], "身分證字號": final_df["身分證"],
                        "收款帳號": final_df["收款帳號"], "交易金額": final_df["實領"],
                        "附言": "薪資", "付款性質": "02"
                    })
                    st.download_button("📥 下載銀行檔", bank_output.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")

    # --- Tab 2 & 3: 店長只能看自己分店的人 ---
    with tab2:
        st.subheader("👤 員工基本資料 (唯讀)")
        if role == 3:
            st.dataframe(df_emp[df_emp['店別'] == shop])
        else:
            st.dataframe(df_emp)

    with tab3:
        st.subheader("🏥 勞健保查詢 (唯讀)")
        if role == 3:
            # 假設 ins_info 裡也有「店別」或我們透過 emp_info 過濾姓名
            my_emp_names = df_emp[df_emp['店別'] == shop]['姓名'].tolist()
            st.dataframe(df_ins[df_ins['姓名'].isin(my_emp_names)])
        else:
            st.dataframe(df_ins)

if __name__ == "__main__":
    main()
