import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心工具 ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {
        "月份": "月份", "生效月份": "生效月份", "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期",
        "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計",
        "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "收款帳號": "收款帳號"
    }
    new_mapping = {c: mapping[k] for c in df.columns for k in mapping if k in c}
    df = df.rename(columns=new_mapping)
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns: 
                df[col] = 0 if any(x in col for x in ["獎金", "津貼", "合計", "補貼", "訪", "負擔", "勞保", "健保", "人數"]) else ""
    return df.loc[:, ~df.columns.duplicated()]

# 💡 網銀格式：附言與付款性質改為「轉帳存入」
def generate_bank_csv(df_source, df_employee, target_m):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), 
        "轉帳項目": "901", 
        "企業編號": "75440263",
        "員工姓名": f_df["姓名"], 
        "身分證字號": f_df["身分證"], 
        "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], 
        "附言": "轉帳存入", 
        "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 - 雙單位發薪管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear(); st.rerun()

    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))
    INS_COLS = ['生效月份', '姓名', '身分證', '勞保', '健保', '健保人數', '勞健保個人負擔', '加保日期']

    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=300), expected_cols=['姓名', '單位', '店別', '身分證', '收款帳號', '基本薪資合計', '執照津貼', '車資補貼'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=300), expected_cols=['月份', '店別', '姓名', '備註'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=300), expected_cols=INS_COLS)
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=300))
    except Exception as e:
        st.error(f"❌ 雲端讀取失敗: {e}"); st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["管理端登入", "員工薪資查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("管理帳號"); pw = st.text_input("管理密碼", type="password")
            if st.button("登入後台"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): 
                        shop_id = re.findall(r'\d+', acc)
                        st.session_state.auth, st.session_state.shop = 3, (shop_id[0].zfill(2) if shop_id else "00")
                    st.rerun()
                else: st.error("❌ 帳密錯誤")
        elif mode == "員工薪資查詢":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, match.iloc[0]['姓名'], "PERSONAL"
                    st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # 員工專區
        name = st.session_state.user_name
        emp_match = df_emp[df_emp['姓名'] == name]
        if not emp_match.empty:
            emp_info = emp_match.iloc[0]
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            df_s = df_ins[df_ins['姓名'] == name].sort_values(['生效月份'], ascending=False)
            p_pay = p_pay.merge(df_s[['生效月份', '勞健保個人負擔']], left_on='月份', right_on='生效月份', how='left')
            for c in ALL_VAR_COLS + ['勞健保個人負擔', '基本薪資合計', '執照津貼', '車資補貼']:
                if c in emp_info.index: p_pay[c] = emp_info[c]
                p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
            bonus_cols = PHARMACY_VAR if str(emp_info['單位']).strip() == "藥局" else CASE_MGR_VAR
            p_pay['實領總額'] = (p_pay['基本薪資合計'] + p_pay['執照津貼'] + p_pay['車資補貼'] + p_pay[bonus_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
            st.dataframe(p_pay[['月份', '姓名', '基本薪資合計', '實領總額', '備註']])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        if role == 4: # 會計
            t_acct = st.tabs(["🏥 勞健保明細維護", "👤 全體員工名單"])
            with t_acct[0]:
                e_ins = st.data_editor(df_ins[INS_COLS], num_rows="dynamic", key="acct_edit")
                if st.button("💾 同步更新勞健保資料"):
                    conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("已更新")
            with t_acct[1]:
                df_view = df_emp[["店別", "姓名", "單位", "身分證"]].copy()
                df_view['店別'] = df_view['店別'].astype(str)
                st.dataframe(df_view.sort_values("店別"))

        else: # 老闆 (1) 與 店長 (3)
            # 【核心修正】：店長不顯示「帳號管理」標籤
            admin_tabs = ["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄檢視"]
            if role == 1: admin_tabs.append("🔑 帳號管理")
            
            tabs = st.tabs(admin_tabs)
            
            with tabs[0]: # 薪資作業
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理"):
                        nm = st.text_input("建立新月份", "2026-06")
                        if st.button("執行建立"):
                            latest_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            df_t = df_emp[['姓名']].merge(latest_rem, on='姓名', how='left')
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_t["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        all_m_raw = df_pay['月份'].dropna().unique().tolist()
                        all_m_safe = sorted([str(m) for m in all_m_raw if str(m).strip() != ""], reverse=True)
                        if all_m_safe:
                            st.markdown("---")
                            del_m = st.selectbox("選擇刪除月份", all_m_safe, key="del_selector")
                            if st.button("🔥 執行永久刪除") and st.checkbox(f"我確認要刪除 {del_m}"):
                                conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m]); st.cache_data.clear(); st.rerun()

                target_m = st.sidebar.selectbox("月份切換", sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if not df_pay.empty else ["無"], key="target_box")
                if target_m != "無":
                    df_s = df_ins[df_ins['生效月份'].astype(str) <= target_m].sort_values(['姓名', '生效月份'], ascending=[True, False])
                    l_ins = df_s.drop_duplicates('姓名')[['姓名', '勞健保個人負擔']]
                    curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                    if role == 3:
                        df_emp['店別_對齊'] = df_emp['店別'].apply(lambda x: str(x).zfill(2))
                        emp_in_shop = df_emp[df_emp['店別_對齊'] == shop]['姓名'].tolist()
                        curr = curr[curr['姓名'].isin(emp_in_shop)]
                    
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼']], on='姓名', how='left')
                    curr = curr.merge(l_ins, on='姓名', how='left')
                    curr = curr.loc[:, ~curr.columns.duplicated()] 
                    
                    for c in ALL_VAR_COLS + ['基本薪資合計', '執照津貼', '車資補貼', '勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']

                    st.subheader(f"📅 {target_m} 薪資編輯區")
                    if role == 1:
                        unit_f = st.radio("顯示過濾", ["全部", "藥局", "個管師"], horizontal=True)
                        display_df = curr.copy()
                        if unit_f != "全部":
                            display_df = display_df[display_df['單位'] == unit_f]
                            active_vars = PHARMACY_VAR if unit_f == "藥局" else CASE_MGR_VAR
                            base_info = ["基本薪資合計"] if unit_f == "藥局" else ["基本薪資合計", "執照津貼", "車資補貼"]
                            cols = ["月份", "店別", "姓名"] + base_info + active_vars + ["勞健保個人負擔", "應付金額", "備註"]
                            display_df = display_df[[c for c in cols if c in display_df.columns]]
                    else:
                        display_df = curr.copy()
                        unit_type = "藥局" if not display_df.empty and str(display_df.iloc[0]['單位']).strip() == "藥局" else "個管師"
                        active_vars = PHARMACY_VAR if unit_type == "藥局" else CASE_MGR_VAR
                        cols = ["月份", "店別", "姓名"] + active_vars + ["備註"]
                        display_df = display_df[[c for c in cols if c in display_df.columns]]

                    edited = st.data_editor(display_df, key="main_edit", num_rows="dynamic")

                    if st.button("💾 同步薪資存檔"):
                        for idx, row in edited.iterrows():
                            target_name = row['姓名']
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註":
                                    df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == target_name), col] = row[col]
                        conn.update(worksheet=PAY_SHEET, data=df_pay); st.cache_data.clear(); st.success("已存檔")

                    if role == 1:
                        st.markdown("---")
                        c1, c2 = st.columns(2)
                        with c1:
                            df_ph = curr[curr['單位'] == "藥局"]
                            if not df_ph.empty: st.download_button("📥 藥局網銀檔", generate_bank_csv(df_ph, df_emp, target_m), f"Phar_{target_m}.csv")
                        with c2:
                            df_cm = curr[curr['單位'] == "個管師"]
                            if not df_cm.empty: st.download_button("📥 個管師網銀檔", generate_bank_csv(df_cm, df_emp, target_m), f"Case_{target_m}.csv")

            with tabs[1]: # 員工資料
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 更新員工資料庫"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
                else: 
                    df_emp['店別_對齊'] = df_emp['店別'].apply(lambda x: str(x).zfill(2))
                    st.dataframe(df_emp[df_emp['店別_對齊'] == shop])
            
            with tabs[2]: st.dataframe(df_ins[INS_COLS].sort_values(['姓名', '生效月份'], ascending=[True, False]))
            
            # 【關鍵】：只有老闆能進 tabs[3]
            if role == 1:
                with tabs[3]: st.dataframe(df_acc[["姓名", "帳號", "身分證"]])

if __name__ == "__main__":
    main()
