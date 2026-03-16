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

# 自動修正欄位名稱工具
def clean_df(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    col_map = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    col_map.update({c: "姓名" for c in df.columns if "姓名" in c})
    col_map.update({c: "月份" for c in df.columns if "月份" in c})
    return df.rename(columns=col_map)

def main():
    st.title("🚀 天康連鎖藥局 - 全功能雲端管理系統")

    # 建立雲端連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 登入邏輯
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, user.split("_")[1]
            st.rerun()
        return

    # --- 讀取三大分頁 ---
    df_pay = clean_df(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = clean_df(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = clean_df(conn.read(worksheet=INS_SHEET, ttl="0"))

    role = st.session_state.auth
    shop = st.session_state.shop

    tab1, tab2, tab3 = st.tabs(["💰 薪資作業與匯出", "👤 員工基本資料", "🏥 勞健保查詢"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
        st.sidebar.header("⚙️ 管理功能")
        
        # 1. 自動建立新月份 (老闆專屬)
        if role == 1:
            with st.sidebar.expander("➕ 自動開啟新月份"):
                new_month = st.text_input("輸入新月份 (如 2026-04)", "2026-04")
                if st.button("確認寫入雲端"):
                    if "店別" not in df_emp.columns:
                        st.error("❌ 員工資料表缺少『店別』欄位，請先修正 emp_info")
                    else:
                        new_rows = pd.DataFrame({
                            "月份": [new_month] * len(df_emp),
                            "店別": df_emp["店別"],
                            "姓名": df_emp["姓名"],
                            "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0,
                            "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                        })
                        updated_pay = pd.concat([df_pay, new_rows], ignore_index=True)
                        conn.update(worksheet=PAY_SHEET, data=updated_pay)
                        st.success(f"✅ {new_month} 名單已寫入雲端！")
                        st.rerun()

        # 2. 核對與編輯區域
        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("切換月份", months)
            
            mask = (df_pay['月份'] == target_month)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            current_pay = df_pay[mask].copy()

            st.subheader(f"📍 {target_month} 核對清單")
            mgr_view = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
            display_cols = current_pay.columns if role == 1 else [c for c in mgr_view if c in current_pay.columns]
            
            edited_df = st.data_editor(current_pay[display_cols], num_rows="dynamic", key="editor")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 同步存檔至 Google Sheet"):
                    others = df_pay[~((df_pay['月份'] == target_month) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    final_save = pd.concat([others, edited_df], ignore_index=True)
                    conn.update(worksheet=PAY_SHEET, data=final_save)
                    st.success("✅ 雲端存檔成功！")

            # 3. 匯出銀行發薪檔 (老闆專屬)
            if role == 1:
                with col2:
                    if st.button("🚀 匯出網銀 CSV (自動帶入帳號)"):
                        # 勾稽 emp_info 抓帳號、身分證、本薪
                        final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                        
                        # 計算實領金額 = 本薪 + 獎金
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
                        st.download_button("📥 下載銀行 CSV", bank_output.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")
        else:
            st.warning("目前無資料，請先新增月份。")

    # --- Tab 2: 員工基本資料 ---
    with tab2:
        st.subheader("👤 員工基本資料 (emp_info)")
        st.dataframe(df_emp)

    # --- Tab 3: 勞健保查詢 ---
    with tab3:
        st.subheader("🏥 勞健保與扣款明細 (ins_info)")
        st.dataframe(df_ins)

if __name__ == "__main__":
    main()
