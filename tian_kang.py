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
    # 勞健保欄位對應
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 薪資勞健保自動計算系統")

    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 權限登入 ---
    if 'auth' not in st.session_state:
        user = st.text_input("帳號 (boss 或 mgr_xx)")
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

    # 讀取三大資料表
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    st.sidebar.success(f"📍 身分：{'總公司 (老闆)' if role==1 else f'店長 ({shop})'}")
    if st.sidebar.button("登出"):
        del st.session_state['auth']; st.rerun()

    tab1, tab2, tab3 = st.tabs(["💰 薪資核對與發薪", "👤 員工資料", "🏥 勞健保明細"])

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

        # B. 薪資核對區
        if not df_pay.empty and '月份' in df_pay.columns:
            months = sorted(df_pay['月份'].unique().tolist(), reverse=True)
            target_month = st.sidebar.selectbox("核對月份", months)
            
            mask = (df_pay['月份'] == target_month)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            current_pay = df_pay[mask].copy()

            # 【核心邏輯】合併基本薪資與勞健保自負額
            if not df_emp.empty:
                current_pay = current_pay.merge(df_emp[['姓名', '基本薪資合計']], on='姓名', how='left')
            if not df_ins.empty:
                # 假設 ins_info 裡有 姓名 和 勞健保自負額
                current_pay = current_pay.merge(df_ins[['姓名', '勞健保自負額']], on='姓名', how='left')

            # --- 自動計算實領金額 ---
            bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            for c in bonus_cols + ['基本薪資合計', '勞健保自負額']:
                current_pay[c] = pd.to_numeric(current_pay[c], errors='coerce').fillna(0)
            
            # 公式：(本薪 + 獎金總和) - 勞健保自負額
            current_pay['應付金額'] = (current_pay['基本薪資合計'] + current_pay[bonus_cols].sum(axis=1)) - current_pay['勞健保自負額']

            # 顯示控制
            mgr_cols = ["月份", "店別", "姓名"] + bonus_cols + ["備註"]
            boss_cols = ["月份", "店別", "姓名", "基本薪資合計"] + bonus_cols + ["勞健保自負額", "應付金額", "備註"]
            cols_to_show = boss_cols if role == 1 else mgr_cols
            
            st.subheader(f"📍 {target_month} 核對清單")
            edited_df = st.data_editor(current_pay[cols_to_show], num_rows="dynamic", key="editor")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 同步存檔至雲端"):
                    # 只存獎金欄位，不重複存本薪與勞健保
                    save_df = edited_df[["月份", "店別", "姓名"] + bonus_cols + ["備註"]]
                    others = df_pay[~((df_pay['月份'] == target_month) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True))
                    st.success("✅ 存檔成功 (實領金額已自動連動計算)")

            # C. 老闆匯出銀行檔
            if role == 1:
                with col2:
                    if st.button("🚀 匯出網銀發薪 CSV"):
                        final_df = edited_df.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank_csv = pd.DataFrame({
                            "付款日期": datetime.now().strftime("%Y%m%d"),
                            "轉帳項目": "901",
                            "企業編號": "75440263",
                            "員工姓名": final_df["姓名"],
                            "身分證字號": final_df["身分證"],
                            "收款帳號": final_df["收款帳號"],
                            "交易金額": final_df["應付金額"],
                            "附言": "薪資",
                            "付款性質": "02"
                        })
                        st.download_button("📥 下載銀行 CSV", bank_csv.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_month}.csv")
        else:
            st.warning("請先建立月份資料。")

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
