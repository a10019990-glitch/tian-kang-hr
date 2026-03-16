import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re

# --- 1. 雲端與頁面設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 核心：格式化店別與欄位清洗
def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c})
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 全功能管理系統")

    # 建立連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 權限登入 ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("登入"):
            if user == "boss":
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"):
                shop_id = re.findall(r'\d+', user)
                st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "00"
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # 讀取資料
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    st.sidebar.success(f"📍 登入身分：{'總公司' if role==1 else f'分店店長 ({shop})'}")
    if st.sidebar.button("登出"):
        del st.session_state['auth']; st.rerun()

    tab1, tab2, tab3 = st.tabs(["💰 薪資與發薪", "👤 員工資料", "🏥 勞健保明細"])

    # --- Tab 1: 薪資與發薪 (保留所有按鈕與分級) ---
    with tab1:
        # A. 老闆功能：建立新月份
        if role == 1:
            with st.sidebar.expander("➕ [管理] 建立新月份"):
                new_month = st.text_input("新月份 (如 2026-04)", "2026-04")
                if st.button("確認寫入雲端"):
                    new_rows = pd.DataFrame({
                        "月份": [new_month] * len(df_emp),
                        "店別": df_emp["店別"],
                        "姓名": df_emp["姓名"],
                        "職務加給": 0, "加班津貼": 0, "店毛利成長獎金": 0, "推廣獎金": 0, "輔具推廣獎金": 0, "慢籤成長獎金": 0, "備註": ""
                    })
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_rows], ignore_index=True))
                    st.success(f"✅ {new_month} 已建立"); st.rerun()

        # B. 編輯區
        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("核對月份", months)
            
            mask = (df_pay['月份'] == target_month)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            current_pay = df_pay[mask].copy()

            # 店長看不到隱私欄位
            mgr_view = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
            cols = current_pay.columns if role == 1 else [c for c in mgr_view if c in current_pay.columns]
            
            edited_df = st.data_editor(current_pay[cols], num_rows="dynamic", key="editor")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 同步資料至雲端"):
                    save_mask = (df_pay['月份'] == target_month)
                    if role == 3: save_mask = save_mask & (df_pay['店別'] == shop)
                    others = df_pay[~save_mask]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, edited_df], ignore_index=True))
                    st.success("✅ 存檔成功")

            # C. 老闆功能：銀行匯出
            if role == 1:
                with col2:
                    if st.button("🚀 匯出網銀 CSV"):
                        final_df = current_pay.merge(df_emp[['姓名', '身分證', '收款帳號', '基本薪資合計']], on='姓名', how='left')
                        bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                        for c in bonus_cols: final_df[c] = pd.to_numeric(final_df[c], errors='coerce').fillna(0)
                        final_df['基本薪資合計'] = pd.to_numeric(final_df['基本薪資合計'], errors='coerce').fillna(0)
                        final_df['實領'] = final_df['基本薪資合計'] + final_df[bonus_cols].sum(axis=1)

                        bank_csv = pd.DataFrame({
                            "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
                            "員工姓名": final_df["姓名"], "身分證字號": final_df["身分證"],
                            "收款帳號": final_df["收款帳號"], "交易金額": final_df["實領"], "附言": "薪資", "付款性質": "02"
                        })
                        st.download_button("📥 下載銀行 CSV", bank_csv.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")

    # --- Tab 2 & 3: 資料查詢 (店長僅看自己分店) ---
    with tab2:
        st.dataframe(df_emp[df_emp['店別'] == shop] if role == 3 else df_emp)
    with tab3:
        if role == 3:
            my_names = df_emp[df_emp['店別'] == shop]['姓名'].tolist()
            st.dataframe(df_ins[df_ins['姓名'].isin(my_names)])
        else:
            st.dataframe(df_ins)

if __name__ == "__main__":
    main()
