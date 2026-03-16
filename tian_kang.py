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
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 三表同步自動化系統")

    # 建立連線
    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 權限登入 ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或店號如 mgr_04)")
        if st.button("進入系統"):
            if user == "boss":
                st.session_state.auth, st.session_state.shop = 1, "ALL"
            elif user.startswith("mgr_"):
                shop_id = re.findall(r'\d+', user)
                st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "00"
            st.rerun()
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # 讀取三大資料表 (使用 TTL=0 確保每次都是最新資料)
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    st.sidebar.success(f"📍 身分：{'總公司 (老闆)' if role==1 else f'店長 ({shop})'}")
    if st.sidebar.button("登出系統"):
        del st.session_state['auth']; st.rerun()

    tab1, tab2, tab3 = st.tabs(["💰 薪資作業與匯出", "👤 員工資料同步", "🏥 勞健保明細同步"])

    # --- Tab 1: 薪資作業 ---
    with tab1:
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

        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("切換月份", months)
            mask = (df_pay['月份'] == target_month)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            current_pay = df_pay[mask].copy()

            # 勾稽資料用於計算
            if not df_emp.empty: current_pay = current_pay.merge(df_emp[['姓名', '基本薪資合計']], on='姓名', how='left')
            if not df_ins.empty: current_pay = current_pay.merge(df_ins[['姓名', '勞健保自負額']], on='姓名', how='left')

            bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            for c in bonus_cols + ['基本薪資合計', '勞健保自負額']:
                current_pay[c] = pd.to_numeric(current_pay[c], errors='coerce').fillna(0)
            
            # 計算實領金額
            current_pay['應付金額'] = (current_pay['基本薪資合計'] + current_pay[bonus_cols].sum(axis=1)) - current_pay['勞健保自負額']

            mgr_view = ["月份", "店別", "姓名"] + bonus_cols + ["備註"]
            boss_view = ["月份", "店別", "姓名", "基本薪資合計"] + bonus_cols + ["勞健保自負額", "應付金額", "備註"]
            cols_to_show = boss_view if role == 1 else mgr_view
            
            st.subheader(f"📍 {target_month} 編輯與核對")
            edited_pay = st.data_editor(current_pay[cols_to_show], num_rows="dynamic", key="pay_editor")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 同步薪資至雲端"):
                    save_df = edited_pay[["月份", "店別", "姓名"] + bonus_cols + ["備註"]]
                    others = df_pay[~((df_pay['月份'] == target_month) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True))
                    st.success("✅ 薪資存檔成功！")

            if role == 1:
                with col2:
                    if st.button("🚀 匯出網銀發薪 CSV"):
                        final_df = edited_pay.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank_csv = pd.DataFrame({
                            "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
                            "員工姓名": final_df["姓名"], "身分證字號": final_df["身分證"], "收款帳號": final_df["收款帳號"],
                            "交易金額": final_df["應付金額"], "附言": "薪資", "付款性質": "02"
                        })
                        st.download_button("📥 下載銀行檔", bank_csv.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")

    # --- Tab 2: 員工資料同步 (新增更新功能) ---
    with tab2:
        st.subheader("👤 員工基本資料管理")
        if role == 1:
            edited_emp = st.data_editor(df_emp, num_rows="dynamic", key="emp_editor")
            if st.button("💾 同步『員工資料』至雲端"):
                conn.update(worksheet=EMP_SHEET, data=edited_emp)
                st.success("✅ 員工資料庫已更新！")
        else:
            st.info(f"店長僅供查看 {shop} 店成員資料")
            st.dataframe(df_emp[df_emp['店別'] == shop])

    # --- Tab 3: 勞健保明細同步 (新增更新功能) ---
    with tab3:
        st.subheader("🏥 勞健保自負額管理")
        if role == 1:
            edited_ins = st.data_editor(df_ins, num_rows="dynamic", key="ins_editor")
            if st.button("💾 同步『勞健保明細』至雲端"):
                conn.update(worksheet=INS_SHEET, data=edited_ins)
                st.success("✅ 勞健保資料庫已更新！")
        else:
            st.info(f"店長僅供查看 {shop} 店成員勞健保明細")
            my_names = df_emp[df_emp['店別'] == shop]['姓名'].tolist()
            st.dataframe(df_ins[df_ins['姓名'].isin(my_names)])

if __name__ == "__main__":
    main()
